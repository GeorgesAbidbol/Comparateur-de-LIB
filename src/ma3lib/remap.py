"""Remappage d'attributs : renommer un attribut, changer sa feature ou son ActivationGroup.

Travaille directement sur l'arbre XML d'origine (`FixtureType.xml_root`) pour ne rien perdre de ce
qu'on ne comprend pas, puis réécrit le fichier dans son format d'entrée (GDTF ou XML MA3).

Renommer un attribut renomme aussi les canaux qui le portent : la MA3 et la spec GDTF nomment un
DMXChannel « Geometry_Attribute » (attribut du 1er LogicalChannel). Tous les liens vers ces canaux
sont corrigés : InitialFunction, DefaultChannelFunction, Relations Master/Follower, ModeMaster.

Règles CSV (séparateur « ; », lignes « # » ignorées) :
    attribut;nouveau_nom;feature;groupe
    Led Control;LEDZoneMode;;
    color crossfade speed;;;-          (« - » retire l'ActivationGroup, vide = inchangé)
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

from . import attributs
from .gdtf import FixtureType

LINK_ATTRS = ("InitialFunction", "DefaultChannelFunction", "Master", "Follower", "ModeMaster",
              "DMXChannel")  # DMXChannel : MacroDMXValue des FTMacros GDTF


class RemapError(Exception):
    """Règle impossible à appliquer (attribut absent, collision de noms de canaux...)."""


@dataclass
class Rule:
    attribute: str
    rename: str = ""
    feature: Optional[str] = None
    activation_group: Optional[str] = None  # "" = retirer

    def describe(self) -> str:
        parts = []
        if self.rename:
            parts.append(f"-> {self.rename}")
        if self.feature is not None:
            parts.append(f"feature {self.feature}")
        if self.activation_group is not None:
            parts.append(f"groupe {self.activation_group or '(aucun)'}")
        return f"{self.attribute} : " + ", ".join(parts)


def load_rules(path: str | Path) -> list[Rule]:
    rules = []
    lines = [l for l in Path(path).read_text(encoding="utf-8-sig").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    for row in csv.reader(lines, delimiter=";"):
        row = [c.strip() for c in row] + [""] * 4
        if row[0].lower() == "attribut":
            continue
        rules.append(Rule(row[0], row[1], row[2] or None,
                          None if row[3] == "" else ("" if row[3] == "-" else row[3])))
    return rules


def rules_from_issues(issues: list[attributs.AttrIssue]) -> list[Rule]:
    """Règles proposées par le détecteur (alertes seulement)."""
    return [Rule(i.attribute, i.rename, i.new_feature, i.new_group)
            for i in issues if i.level == "alerte" and i.suggestion]


# --------------------------------------------------------------------------

def _ft_node(ft: FixtureType) -> ET.Element:
    if ft.xml_root is None or ft.xml_root.find("FixtureType") is None:
        raise RemapError("arbre XML d'origine absent")
    return ft.xml_root.find("FixtureType")


def _ensure_groups(node: ET.Element, feature: str, ag: str) -> None:
    """Déclare la feature et l'ActivationGroup s'ils manquent (sinon fichier invalide)."""
    defs = node.find("AttributeDefinitions")
    if ag:
        ags = defs.find("ActivationGroups")
        if ags is None:
            ags = ET.SubElement(defs, "ActivationGroups")
        if not any(g.get("Name") == ag for g in ags):
            ET.SubElement(ags, "ActivationGroup", Name=ag)
    if feature and "." in feature:
        group, feat = feature.split(".", 1)
        fgs = defs.find("FeatureGroups")
        if fgs is None:
            fgs = ET.SubElement(defs, "FeatureGroups")
        fg = next((g for g in fgs if g.get("Name") == group), None)
        if fg is None:
            fg = ET.SubElement(fgs, "FeatureGroup", Name=group, Pretty=group)
        if not any(f.get("Name") == feat for f in fg):
            ET.SubElement(fg, "Feature", Name=feat)


def _set(el: ET.Element, key: str, value: Optional[str]) -> None:
    if value is None:
        return
    if value == "":
        el.attrib.pop(key, None)
    else:
        el.set(key, value)


def _geo_name(channel: ET.Element) -> str:
    return channel.get("Geometry", "").split(".")[-1]


def apply(ft: FixtureType, rules: list[Rule]) -> list[str]:
    """Applique les règles sur ft.xml_root. Renvoie le journal des modifications."""
    node = _ft_node(ft)
    attrs_el = node.find("AttributeDefinitions/Attributes")
    log: list[str] = []
    for rule in rules:
        defs = {a.get("Name"): a for a in attrs_el}
        a = defs.get(rule.attribute)
        if a is None:
            raise RemapError(f"attribut « {rule.attribute} » absent du fixture")
        new = rule.rename or rule.attribute
        if rule.rename and rule.rename != rule.attribute:
            _rename_channels(node, rule.attribute, new, log)
            ref = attributs.ma3_known(new) or attributs.gdtf_standard(new) or {}
            if new in defs:  # l'attribut cible existe déjà : on retire l'ancien
                attrs_el.remove(a)
                a = defs[new]
                log.append(f"définition « {rule.attribute} » retirée, « {new} » existait déjà")
            else:
                a.set("Name", new)
                if ref:
                    a.set("Pretty", ref.get("pretty") or new)
                    a.set("Feature", ref["feature"])
                    _set(a, "ActivationGroup", ref.get("activation_group", ""))
                    _set(a, "PhysicalUnit", ref.get("physical_unit") or None)
                log.append(f"attribut « {rule.attribute} » renommé « {new} »"
                           + (f" ({a.get('Feature')})" if ref else ""))
            for other in attrs_el:  # sous-attributs qui pointaient sur l'ancien
                if other.get("MainAttribute") == rule.attribute:
                    other.set("MainAttribute", new)
        if rule.feature is not None and a.get("Feature") != rule.feature:
            log.append(f"« {new} » : feature {a.get('Feature')} -> {rule.feature}")
            a.set("Feature", rule.feature)
        if rule.activation_group is not None and a.get("ActivationGroup", "") != rule.activation_group:
            log.append(f"« {new} » : ActivationGroup {a.get('ActivationGroup') or '(aucun)'}"
                       f" -> {rule.activation_group or '(aucun)'}")
            _set(a, "ActivationGroup", rule.activation_group)
        _ensure_groups(node, a.get("Feature", ""), a.get("ActivationGroup", ""))
    return log


def _rename_channels(node: ET.Element, old: str, new: str, log: list[str]) -> None:
    for mode in node.iterfind("DMXModes/DMXMode"):
        channels = list(mode.iterfind("DMXChannels/DMXChannel"))
        renames: dict[str, str] = {}
        names = {f"{_geo_name(c)}_{_first_attr(c)}" for c in channels}
        for ch in channels:
            first = _first_attr(ch)  # avant renommage
            for lc in ch.iterfind("LogicalChannel"):
                if lc.get("Attribute", "").split(".")[-1] == old:
                    lc.set("Attribute", new)
                for cf in lc.iterfind("ChannelFunction"):
                    if cf.get("Attribute", "").split(".")[-1] == old:
                        cf.set("Attribute", new)
            if first == old:
                before, after = f"{_geo_name(ch)}_{old}", f"{_geo_name(ch)}_{new}"
                if after in names:
                    raise RemapError(f"mode « {mode.get('Name')} » : le canal {after} existe déjà")
                renames[before] = after
        # DefaultChannelFunction (MA3) = « Logical.Function » ; les autres liens partent du canal :
        # « Canal », « Canal.Logical » ou « Canal.Logical.Function ».
        for el in mode.iter():
            for key in LINK_ATTRS:
                if el.get(key):
                    el.set(key, _relink(el.get(key), renames, old, new,
                                        local=key == "DefaultChannelFunction"))
        if renames:
            log.append(f"mode « {mode.get('Name')} » : {len(renames)} canal(aux) renommé(s)")


def _first_attr(ch: ET.Element) -> str:
    lc = ch.find("LogicalChannel")
    return lc.get("Attribute", "").split(".")[-1] if lc is not None else ""


def _relink(value: str, renames: dict[str, str], old: str, new: str, local: bool = False) -> str:
    segs = value.split(".")
    if segs[0] in renames:
        segs[0] = renames[segs[0]]
        if len(segs) > 1 and segs[1] == old:
            segs[1] = new
    elif local and len(segs) == 2 and segs[0] == old:
        segs[0] = new
    return ".".join(segs)


# --------------------------------------------------------------------------

def save(ft: FixtureType, out: str | Path) -> Path:
    """Écrit le fixture modifié dans le même format que l'original."""
    out = Path(out)
    if ft.source is not None and out.resolve() == Path(ft.source).resolve():
        raise RemapError("on n'écrase jamais le fichier d'origine : choisis un autre nom")
    buf = io.BytesIO()
    ET.ElementTree(ft.xml_root).write(buf, encoding="UTF-8", xml_declaration=True)
    data = buf.getvalue()
    if ft.format == "ma3" or (ft.source and Path(ft.source).suffix.lower() == ".xml"):
        out.write_bytes(data)
        return out
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(ft.source) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, data if item.filename == "description.xml" else src.read(item.filename))
    shutil.move(tmp, out)
    return out
