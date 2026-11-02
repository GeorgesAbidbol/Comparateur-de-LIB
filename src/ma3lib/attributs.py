"""Attributs : référence GDTF / grandMA3 et détection des attributs mal rangés.

Tables de référence (voir tools/build_attribute_tables.py) :
- data/gdtf_attributes.json : annexe B de la spec GDTF 1.2 (280 attributs, avec wildcards (n)/(m)) ;
- data/ma3_attributes.json  : attributs standard vus dans des fixture types exportés par grandMA3
  2.3.2.0. Liste PARTIELLE : la console en définit 366, on ne les a pas encore tous.
  Certains attributs GDTF n'existent pas dans la MA3 (Jo, 02/11/2026) : un attribut absent de
  cette table est signalé « non confirmé MA3 », pas forcément faux.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .gdtf import FixtureType

DATA = Path(__file__).parent / "data"

# Feature attendue pour chaque ActivationGroup standard (spec GDTF, annexe B).
AG_FEATURE_GROUP = {
    "PanTilt": "Position", "XYZ": "Position", "Rot_XYZ": "Position", "Scale_XYZ": "Position",
    "ColorRGB": "Color", "ColorHSB": "Color", "ColorCIE": "Color", "ColorIndirect": "Color",
    "Prism": "Beam", "BeamShaper": "Beam", "Shaper": "Shapers",
}
_AG_WILDCARD = re.compile(r"^(Gobo|AnimationWheel|AnimationSystem)\d+(Pos)?$")


@lru_cache(maxsize=None)
def _table(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _patterns(name: str) -> list[tuple[re.Pattern, str]]:
    out = []
    for key in _table(name):
        rx = re.escape(key).replace(r"\(n\)", r"\d+").replace(r"\(m\)", r"\d+")
        out.append((re.compile(f"^{rx}$", re.I), key))
    return out


# Conversions faites par la MA3 à l'import d'un GDTF (vues dans les XML exportés par la console).
GDTF_TO_MA3 = {"ColorSub_C": "ColorRGB_R", "ColorSub_M": "ColorRGB_G", "ColorSub_Y": "ColorRGB_B"}


def _normalize(name: str) -> str:
    """Renommages MA3 -> GDTF (ColorRGB_R -> ColorAdd_R)."""
    return re.sub(r"^ColorRGB_", "ColorAdd_", name)


def ma3_name(name: str) -> str:
    """Nom que la MA3 donne à un attribut GDTF (ColorAdd_R -> ColorRGB_R, ColorSub_C -> ColorRGB_R)."""
    if name in GDTF_TO_MA3:
        return GDTF_TO_MA3[name]
    alt = re.sub(r"^ColorAdd_", "ColorRGB_", name)
    return alt if alt in _table("ma3_attributes.json") else name


def gdtf_standard(name: str) -> Optional[dict]:
    """Définition GDTF standard de l'attribut (wildcards résolus), ou None si attribut maison."""
    for rx, key in _patterns("gdtf_attributes.json"):
        if rx.match(_normalize(name)) or rx.match(name):
            return {"name": key, **_table("gdtf_attributes.json")[key]}
    return None


def ma3_known(name: str) -> Optional[dict]:
    """Définition MA3 si l'attribut (ou un attribut de la même famille, ex. Gobo3 pour Gobo1)
    a été vu dans un export grandMA3 2.3.2.0."""
    ma3 = _table("ma3_attributes.json")
    for n in (name, ma3_name(name)):
        if n in ma3:
            return ma3[n]
    std = gdtf_standard(name)
    if std is None:
        return None
    rx = next(r for r, k in _patterns("gdtf_attributes.json") if k == std["name"])
    for key, val in ma3.items():
        if rx.match(_normalize(key)):
            return val
    return None


def _group(feature: str) -> str:
    return feature.split(".")[0] if feature else ""


def _ag_group(ag: str) -> str:
    if ag in AG_FEATURE_GROUP:
        return AG_FEATURE_GROUP[ag]
    return "Gobo" if _AG_WILDCARD.match(ag) else ""


# Synonymes fabricant -> vocabulaire GDTF/MA3, pour proposer des équivalents aux attributs maison.
SYNONYMS = {
    "chase": {"effects"}, "pattern": {"effects"}, "fx": {"effects"}, "effect": {"effects"},
    "macro": {"effects", "macro"}, "speed": {"rate", "speed"}, "crossfade": {"fade"},
    "transition": {"fade"}, "size": {"adjust"}, "step": {"rate"}, "intensity": {"dimmer"},
    "back": {"background"}, "colour": {"color"}, "strobe": {"strobe", "shutter"},
}


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[A-Za-z][a-z]*", re.sub(r"([a-z])([A-Z])", r"\1 \2", name))
    out = set()
    for w in (w.lower() for w in words):
        if len(w) > 1:
            out.add(w)
            out |= SYNONYMS.get(w, set())
    return out


def candidates(name: str, feature: str = "", limit: int = 3) -> list[str]:
    """Attributs standard qui pourraient remplacer un attribut maison, les plus probables d'abord.
    Simple proposition par les mots du nom : c'est à Jo de choisir (jamais appliqué par --auto)."""
    want = _tokens(name)
    scored = []
    for key, val in _table("gdtf_attributes.json").items():
        concrete = key.replace("(n)", "1").replace("(m)", "1")
        common = want & _tokens(concrete)
        if not common:
            continue
        score = 2 * len(common) - 0.5 * len(_tokens(concrete) - want)
        if feature and _group(val["feature"]) == _group(feature):
            score += 1
        if ma3_known(concrete):
            score += 1
        scored.append((score, ma3_name(concrete)))
    scored.sort(key=lambda x: -x[0])
    return [n for sc, n in scored[:limit] if sc > 1]


@dataclass
class AttrIssue:
    attribute: str
    feature: str
    activation_group: str
    problem: str
    level: str = "alerte"  # « alerte » ou « info »
    rename: str = ""  # suggestion : nouveau nom d'attribut
    new_feature: Optional[str] = None
    new_group: Optional[str] = None  # "" = retirer l'ActivationGroup
    equivalents: tuple[str, ...] = ()  # attributs MA3/GDTF possibles pour un attribut maison

    @property
    def suggestion(self) -> str:
        parts = []
        if self.rename:
            parts.append(f"renommer en {self.rename}")
        if self.new_feature is not None:
            parts.append(f"feature {self.new_feature}")
        if self.new_group is not None:
            parts.append(f"ActivationGroup {self.new_group or '(aucun)'}")
        return ", ".join(parts)


def used_attributes(ft: FixtureType) -> dict[str, Counter]:
    """Attributs utilisés par les canaux logiques -> attributs de leurs ChannelFunctions."""
    used: dict[str, Counter] = {}
    for mode in ft.modes:
        for ch in mode.channels:
            for lc in ch.logical_channels:
                c = used.setdefault(lc.attribute, Counter())
                for cf in lc.functions:
                    c[cf.attribute] += 1
    return used


def check(ft: FixtureType) -> list[AttrIssue]:
    issues: list[AttrIssue] = []
    for name, functions in used_attributes(ft).items():
        a = ft.attributes.get(name)
        feature = a.feature if a else ""
        ag = a.activation_group if a else ""
        std = gdtf_standard(name)
        if std is not None:
            known = ma3_known(name)
            ref = known or std
            if _group(ref["feature"]) != _group(feature) or ref["activation_group"] != ag:
                # La MA3 remplace la définition d'un attribut d'usine par la sienne (vérifié sur
                # l'Esprite : Color1 perd son groupe ColorRGB, Prism1Pos gagne Prism) : sans effet
                # sur console, mais à corriger pour un GDTF propre.
                issues.append(AttrIssue(
                    name, feature, ag,
                    f"attribut standard rangé en {feature or '?'} / {ag or 'sans groupe'}, "
                    f"la référence dit {ref['feature']} / {ref['activation_group'] or 'sans groupe'}"
                    + (" (la MA3 corrige d'elle-même à l'import)" if known else ""),
                    level="info" if known else "alerte",
                    new_feature=ref["feature"] if _group(ref["feature"]) != _group(feature) else None,
                    new_group=ref["activation_group"] if ref["activation_group"] != ag else None))
            elif not ma3_known(name):
                issues.append(AttrIssue(name, feature, ag,
                                        "attribut GDTF jamais vu dans la MA3 2.3.2.0 (à confirmer)",
                                        level="info"))
            continue
        # attribut maison du fabricant
        problems, rename, new_feature, new_group = [], "", None, None
        inner = [f for f in functions if f not in (name, "NoFeature") and gdtf_standard(f)]
        if len(set(inner)) == 1:
            target = inner[0]
            tdef = ma3_known(target) or gdtf_standard(target)
            if ma3_known(target):
                problems.append(f"ses fonctions sont du {target} ({tdef['feature']})")
                rename = ma3_name(target)
            elif _group(tdef["feature"]) != _group(feature):
                problems.append(f"ses fonctions sont du {target} ({tdef['feature']}, attribut non "
                                f"confirmé MA3 : on garde le nom et on corrige la feature)")
                new_feature = tdef["feature"]
        agg = _ag_group(ag)
        if ag and agg and agg != _group(feature):
            problems.append(f"ActivationGroup {ag} incohérent avec la feature {feature}")
            if not rename:
                new_group = ""
        if problems:
            issues.append(AttrIssue(name, feature, ag, "attribut maison : " + " ; ".join(problems),
                                    rename=rename, new_feature=new_feature, new_group=new_group))
        elif ag and agg:
            issues.append(AttrIssue(name, feature, ag,
                                    f"attribut maison dans le groupe d'usine {ag} : il s'active avec "
                                    f"les attributs {ag}", level="info"))
        else:
            issues.append(AttrIssue(name, feature, ag, "attribut maison (hors liste GDTF)", level="info"))
    for i in issues:
        if gdtf_standard(i.attribute) is None and not i.rename:
            i.equivalents = tuple(candidates(i.attribute, i.feature))
    return issues
