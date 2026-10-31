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
    per_mode_variants: bool = False  # chaque membre sert à des modes différents
    wrapped_template: str = ""  # membres = enveloppes autour d'une référence vers ce modèle

    @property
    def convertible(self) -> bool:
        return (not self.per_mode_variants and bool(self.same_channels)
                and all(self.same_channels.values()))


def diagnose(ft: FixtureType) -> list[Finding]:
    findings: list[Finding] = []
    findings += _check_names(ft)
    findings += _check_references(ft)
    findings += _check_mode_links(ft)
    findings += _check_instances(ft)
    findings += _check_dimmer(ft)
    findings += _check_3d_only(ft)
    findings += _check_duplicate_templates(ft)
    findings += _check_kind_mismatch(ft)
    return findings


def _check_kind_mismatch(ft: FixtureType) -> list[Finding]:
    """Géométries jumelles (mêmes canaux, même nombre d'enfants) de types différents,
    ex. segment A en Beam et segment B en Geometry. Pour Jo, tout ce qui émet de la
    lumière doit être un Beam (simulation 3D) : on propose d'aligner sur Beam."""
    out: list[Finding] = []
    by_name = {g.name: g for g in ft.all_geometries()}
    for mode in ft.modes:
        attrs: dict[str, list[str]] = defaultdict(list)
        for ch in mode.channels:
            attrs[ch.geometry] += [lc.attribute for lc in ch.logical_channels]
        twins: dict[tuple, list[Geometry]] = defaultdict(list)
        for name, a in attrs.items():
            g = by_name.get(name)
            if g is None or g.is_reference or g.name == mode.geometry:
                continue
            twins[(tuple(sorted(a)), len(g.children))].append(g)
        for members in twins.values():
            kinds = {g.kind for g in members}
            if len(kinds) > 1:
                target = "Beam" if "Beam" in kinds else sorted(kinds)[0]
                odd = [f"{g.name} [{g.kind}] -> {target}" for g in members if g.kind != target]
                out.append(Finding(
                    ALERTE, "types_incoherents",
                    f"Mode « {mode.name} » : géométries jumelles de types différents "
                    f"({', '.join(sorted(kinds))}), à aligner sur {target}",
                    odd,
                ))
    return out


def duplicate_templates(ft: FixtureType) -> list[list[str]]:
    """Modèles de référence qui décrivent le même type d'instance (même type de
    géométrie, mêmes attributs de canaux) sous des noms différents, un par mode.
    Règle de Jo : un seul modèle (ex. « Pixel RGB ») partagé par tous les modes.

    Deux modèles identiques utilisés dans un même mode ne sont PAS signalés :
    c'est voulu quand ils décrivent des modules physiques distincts
    (JDC Line = 2 modules JDC 500 collés : « RGB Pix A » et « RGB Pix B »).
    """
    referenced = {g.reference for g in ft.all_geometries() if g.is_reference}
    by_key: dict[tuple, list[str]] = defaultdict(list)
    modes_of: dict[str, set[str]] = {}
    for name in sorted(referenced):
        tpl = ft.top_level(name)
        if tpl is None:
            continue
        names = _subtree_names(tpl)
        attrs: set[str] = set()
        modes_of[name] = set()
        for mode in ft.modes:
            here = {lc.attribute for ch in mode.channels if ch.geometry in names
                    for lc in ch.logical_channels}
            if here:
                attrs |= here
                modes_of[name].add(mode.name)
        if not attrs:
            continue  # modèle purement visuel : traité par geometries_3d_only
        by_key[(_signature(tpl), tuple(sorted(attrs)))].append(name)

    groups: list[list[str]] = []
    for names in by_key.values():
        # composantes connexes : on relie deux modèles s'ils ne partagent aucun mode
        todo, seen = list(names), set()
        while todo:
            start = todo.pop(0)
            if start in seen:
                continue
            comp, stack = [], [start]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                comp.append(cur)
                stack += [o for o in names if o not in seen and modes_of[o].isdisjoint(modes_of[cur])]
            if len(comp) > 1:
                groups.append(sorted(comp))
    return groups


def _check_duplicate_templates(ft: FixtureType) -> list[Finding]:
    groups = duplicate_templates(ft)
    if not groups:
        return []
    return [Finding(
        ALERTE, "modeles_en_double",
        f"{len(groups)} type(s) d'instance décrit(s) par plusieurs modèles de référence "
        "(un par mode) : à fusionner en un seul modèle partagé",
        [" = ".join(g) for g in groups],
    )]


def useful_geometries(ft: FixtureType) -> set[str]:
    """Géométries utiles au pilotage : racines de mode, géométries portant un canal,
    leurs parents, et les références vers un modèle qui porte des canaux."""
    useful: set[str] = {m.geometry for m in ft.modes}
    useful |= {ch.geometry for m in ft.modes for ch in m.channels}
    changed = True
    while changed:
        before = len(useful)
        for g in ft.all_geometries():
            if g.name in useful:
                continue
            if any(c.name in useful for c in g.walk() if c is not g):
                useful.add(g.name)
            elif g.is_reference and g.reference in useful:
                useful.add(g.name)
        changed = len(useful) != before
    return useful


def geometries_3d_only(ft: FixtureType) -> list[Geometry]:
    """Sous-arbres qui ne portent aucun canal dans aucun mode (pur visuel 3D).
    Ne renvoie que le sommet de chaque sous-arbre supprimable."""
    useful = useful_geometries(ft)
    out: list[Geometry] = []

    def visit(g: Geometry) -> None:
        if g.name not in useful:
            out.append(g)
            return
        for c in g.children:
            visit(c)

    for root in ft.geometries:
        visit(root)
    return out


def _check_3d_only(ft: FixtureType) -> list[Finding]:
    if not ft.modes:
        return []
    tops = geometries_3d_only(ft)
    if not tops:
        return []
    total = sum(1 for g in tops for _ in g.walk())
    refs = sum(1 for g in tops for x in g.walk() if x.is_reference)
    msg = f"{total} géométrie(s) sans aucun canal, uniquement pour la 3D : supprimables au nettoyage"
    if refs:
        msg += f" (dont {refs} référence(s))"
    return [Finding(ALERTE, "geometries_3d_seulement", msg,
                    [f"{g.path()} [{g.kind}]" + (f" + {sum(1 for _ in g.walk()) - 1} enfant(s)" if g.children else "")
                     for g in tops])]


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
        out.append(Finding(INFO, "geometrie_orpheline",
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
    """Repère les géométries sœurs identiques dont le nom ne diffère que par un numéro.

    Ignorés : les groupes sans aucun canal (connecteurs, câblage...).
    Signalés à part : les variantes par mode (une copie de l'arbre par mode DMX),
    qui ne sont pas des instances.
    """
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
            modes_of: list[set[str]] = [set() for _ in members]
            for mode in ft.modes:
                per_instance = [_attrs_on(mode, _subtree_names(m)) for m in members]
                for i, attrs in enumerate(per_instance):
                    if attrs:
                        modes_of[i].add(mode.name)
                if any(per_instance):
                    group.same_channels[mode.name] = all(p == per_instance[0] for p in per_instance)
            if not group.same_channels:
                continue  # aucun canal : rien à gagner
            group.per_mode_variants = all(modes_of) and all(
                modes_of[i].isdisjoint(modes_of[j])
                for i in range(len(members)) for j in range(i + 1, len(members)))
            group.wrapped_template = _wrapped_template(members)
            groups.append(group)
    return groups


def _wrapped_template(members: list[Geometry]) -> str:
    """Si chaque membre contient une référence vers le même modèle, renvoie ce modèle."""
    targets = set()
    for m in members:
        refs = [g.reference for g in m.walk() if g.is_reference]
        if len(refs) != 1:
            return ""
        targets.add(refs[0])
    return targets.pop() if len(targets) == 1 else ""


def _check_instances(ft: FixtureType) -> list[Finding]:
    out: list[Finding] = []
    variants = []
    for grp in find_instance_groups(ft):
        if grp.per_mode_variants:
            variants.append(f"{grp.names[0]} … {grp.names[-1]} ({len(grp.names)})")
            continue
        detail = [f"{len(grp.names)} géométries sous {grp.parent} : {grp.names[0]} … {grp.names[-1]}"]
        detail += [f"mode « {m} » : {'canaux identiques' if ok else 'canaux différents'}"
                   for m, ok in grp.same_channels.items()]
        if grp.convertible and grp.wrapped_template:
            out.append(Finding(
                ALERTE, "references_sans_canaux",
                f"{len(grp.names)} instances enveloppent une référence vers « {grp.wrapped_template} » "
                "mais gardent chacune leurs propres canaux : la référence ne sert qu'au visuel "
                "(convertibles en vraies références avec Breaks)",
                detail,
            ))
        elif grp.convertible:
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
    if variants:
        out.append(Finding(
            INFO, "variantes_par_mode",
            f"{len(variants)} groupe(s) de géométries dupliquées par mode DMX "
            "(une copie de l'arbre par mode : mutualisables quand on retravaille ces modes)",
            variants,
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
