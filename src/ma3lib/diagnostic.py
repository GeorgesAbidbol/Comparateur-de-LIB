"""Diagnostic d'un fixture type GDTF : géométries, références, dimmer.

Ne modifie rien : produit une liste de constats que l'interface affichera
et que le nettoyeur (étape 3) utilisera comme point de départ.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .gdtf import DMXMode, FixtureType, Geometry

ERREUR = "erreur"
ALERTE = "alerte"
INFO = "info"

# Attributs de couleur qui justifient un dimmer virtuel quand il n'y a pas de Dimmer.
COLOR_MIX = re.compile(r"^(ColorAdd_|ColorRGB_|ColorSub_)")
DIGITS = re.compile(r"\d+")


@dataclass
class Finding:
    level: str
    code: str
    message: str
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"[{self.level}] {self.message}"


@dataclass
class InstanceGroup:
    """Géométries sœurs identiques : candidates à « 1 modèle + N références »."""

    parent: str
    names: list[str]
    signature: str
    same_channels: dict[str, bool] = field(default_factory=dict)  # mode -> ok

    @property
    def convertible(self) -> bool:
        return bool(self.same_channels) and all(self.same_channels.values())


def diagnose(ft: FixtureType) -> list[Finding]:
    findings: list[Finding] = []
    findings += _check_names(ft)
    findings += _check_references(ft)
    findings += _check_mode_links(ft)
    findings += _check_instances(ft)
    findings += _check_dimmer(ft)
    return findings


# --------------------------------------------------------------------------

def _check_names(ft: FixtureType) -> list[Finding]:
    counts = Counter(g.name for g in ft.all_geometries())
    dupes = sorted(n for n, c in counts.items() if c > 1)
    if not dupes:
        return []
    return [Finding(
        ERREUR, "noms_dupliques",
        f"{len(dupes)} nom(s) de géométrie utilisé(s) plusieurs fois (la spec exige des noms uniques)",
        dupes,
    )]


def _check_references(ft: FixtureType) -> list[Finding]:
    out: list[Finding] = []
    top = {g.name for g in ft.geometries}
    every = {g.name for g in ft.all_geometries()}
    refs = [g for g in ft.all_geometries() if g.is_reference]
    missing = [f"{g.path()} -> {g.reference}" for g in refs if g.reference not in every]
    not_top = [f"{g.path()} -> {g.reference}" for g in refs if g.reference in every and g.reference not in top]
    if missing:
        out.append(Finding(ERREUR, "reference_cassee",
                           f"{len(missing)} référence(s) vers une géométrie inexistante", missing))
    if not_top:
        out.append(Finding(ERREUR, "reference_non_racine",
                           f"{len(not_top)} référence(s) vers une géométrie qui n'est pas au premier niveau",
                           not_top))
    if refs:
        targets = Counter(g.reference for g in refs)
        out.append(Finding(INFO, "references",
                           f"{len(refs)} référence(s) de géométrie vers {len(targets)} modèle(s)",
                           [f"{t} : {n} instance(s)" for t, n in sorted(targets.items())]))
    return out


def _check_mode_links(ft: FixtureType) -> list[Finding]:
    out: list[Finding] = []
    every = {g.name for g in ft.all_geometries()}
    top = {g.name for g in ft.geometries}
    used_tops: set[str] = set()
    for mode in ft.modes:
        if mode.geometry not in top:
            out.append(Finding(ERREUR, "mode_sans_racine",
                               f"Mode « {mode.name} » : géométrie racine « {mode.geometry} » introuvable"))
        used_tops.add(mode.geometry)
        unknown = sorted({ch.geometry for ch in mode.channels if ch.geometry not in every})
        if unknown:
            out.append(Finding(ERREUR, "canal_sans_geometrie",
                               f"Mode « {mode.name} » : {len(unknown)} canal(aux) liés à une géométrie inexistante",
                               unknown))
    used_tops.update(g.reference for g in ft.all_geometries() if g.is_reference)
    orphans = sorted(top - used_tops)
    if orphans and ft.modes:
        out.append(Finding(ALERTE, "geometrie_orpheline",
                           f"{len(orphans)} géométrie(s) de premier niveau utilisée(s) par aucun mode ni référence",
                           orphans))
    return out


def _signature(g: Geometry) -> str:
    """Empreinte d'une géométrie sans tenir compte des numéros dans les noms."""
    kids = ",".join(_signature(c) for c in g.children)
    ref = DIGITS.sub("#", g.reference) if g.is_reference else ""
    return f"{g.kind}:{g.model}:{ref}[{kids}]"


def _subtree_names(g: Geometry) -> set[str]:
    return {x.name for x in g.walk()}


def _attrs_on(mode: DMXMode, names: set[str]) -> list[str]:
    return sorted(ch.attribute for ch in mode.channels if ch.geometry in names)


def find_instance_groups(ft: FixtureType, min_size: int = 2) -> list[InstanceGroup]:
    """Repère les géométries sœurs identiques dont le nom ne diffère que par un numéro."""
    groups: list[InstanceGroup] = []
    parents: list[tuple[str, list[Geometry]]] = [("(racine)", ft.geometries)]
    parents += [(g.path(), g.children) for g in ft.all_geometries() if g.children]
    for parent_path, siblings in parents:
        buckets: dict[tuple[str, str], list[Geometry]] = defaultdict(list)
        for g in siblings:
            if g.is_reference:
                continue  # déjà fait proprement
            stem = DIGITS.sub("#", g.name)
            if stem == g.name:
                continue  # pas de numéro : pas une instance
            buckets[(stem, _signature(g))].append(g)
        for (_, sig), members in buckets.items():
            if len(members) < min_size:
                continue
            group = InstanceGroup(parent=parent_path, names=[m.name for m in members], signature=sig)
            for mode in ft.modes:
                per_instance = [_attrs_on(mode, _subtree_names(m)) for m in members]
                if any(per_instance):
                    group.same_channels[mode.name] = all(p == per_instance[0] for p in per_instance)
            groups.append(group)
    return groups


def _check_instances(ft: FixtureType) -> list[Finding]:
    out: list[Finding] = []
    for grp in find_instance_groups(ft):
        detail = [f"{len(grp.names)} géométries sous {grp.parent} : {grp.names[0]} … {grp.names[-1]}"]
        detail += [f"mode « {m} » : {'canaux identiques' if ok else 'canaux différents'}"
                   for m, ok in grp.same_channels.items()]
        if grp.convertible:
            out.append(Finding(
                ALERTE, "instances_sans_reference",
                f"{len(grp.names)} instances copiées au lieu d'utiliser des géométries références "
                f"(convertibles en 1 modèle + {len(grp.names)} références)",
                detail,
            ))
        else:
            out.append(Finding(
                INFO, "instances_similaires",
                f"{len(grp.names)} géométries sœurs identiques, mais leurs canaux diffèrent : "
                "conversion à vérifier à la main",
                detail,
            ))
    return out


def _ancestors(ft: FixtureType, name: str) -> set[str]:
    """La géométrie et tous ses parents, y compris à travers les références
    (les attributs « descendent » dans l'arbre : un Dimmer sur Body couvre ses pixels)."""
    seen: set[str] = set()
    todo = [name]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        for g in ft.all_geometries():
            if g.name == current and g.parent is not None:
                todo.append(g.parent.name)
            if g.is_reference and g.reference == current:
                todo.append(g.name)
    return seen


def _check_dimmer(ft: FixtureType) -> list[Finding]:
    out: list[Finding] = []
    for mode in ft.modes:
        virtual = [ch.name for ch in mode.channels if ch.is_virtual]
        if virtual:
            out.append(Finding(INFO, "canaux_virtuels",
                               f"Mode « {mode.name} » : {len(virtual)} canal(aux) virtuel(s)", virtual))
        by_geo: dict[str, set[str]] = defaultdict(set)
        for ch in mode.channels:
            for lc in ch.logical_channels:
                by_geo[ch.geometry].add(lc.attribute)
        dimmed = {geo for geo, attrs in by_geo.items() if "Dimmer" in attrs}
        needs = sorted(
            geo for geo, attrs in by_geo.items()
            if any(COLOR_MIX.match(a) for a in attrs) and not (_ancestors(ft, geo) & dimmed)
        )
        has_any_dimmer = any("Dimmer" in attrs for attrs in by_geo.values())
        if needs:
            where = "aucun dimmer dans le mode" if not has_any_dimmer else "dimmer absent sur ces géométries"
            out.append(Finding(
                ALERTE if not has_any_dimmer else INFO, "dimmer_virtuel_possible",
                f"Mode « {mode.name} » : couleur sans dimmer sur {len(needs)} géométrie(s) ({where}), "
                "dimmer virtuel possible",
                needs,
            ))
    return out
