"""Correction de la charte DMX depuis l'atelier (Jo, 11/11/2026) : les canaux d'une géométrie
dans un mode, qu'on peut déplacer, passer en 16 bits, changer d'attribut, ajouter ou retirer.

Tout se fait sur l'arbre XML d'origine (rien de ce qu'on ne comprend pas n'est perdu), après
vérification ; le fixture est relu à la fin. GDTF et XML MA3 (Jo, 13/11/2026 : « sur les fichiers
de la console aussi ») : MA3 écrit les octets en Coarse/Fine/Ultra/Uber, la géométrie en chemin
pointé (« Base.Yoke.Head »), les valeurs sur 24 bits en hexadécimal (« 80007F »).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from . import attributs, geotree, remap
from .gdtf import FixtureType, Geometry
from .geotree import MoveError


@dataclass
class Ligne:
    """Un canal tel que l'atelier l'affiche."""
    attribute: str
    offsets: list[int]  # [coarse, fine…] ; vide = canal virtuel
    default: str  # valeur par défaut telle qu'écrite (« 0/1 »)
    geometry: str  # géométrie (ou modèle) qui porte le canal

    @property
    def bits(self) -> int:
        return 8 * max(1, len(self.offsets))


def carrier(g: Geometry) -> str:
    """La géométrie qui porte les canaux : pour une référence, son modèle."""
    return g.reference if g.is_reference else g.name


_BYTES = ("Coarse", "Fine", "Ultra", "Uber")  # octets d'un canal MA3


def _mode_el(ft: FixtureType, mode_name: str, read: bool = False) -> ET.Element:
    if ft.xml_root is None:
        raise MoveError("fixture sans arbre XML")
    for m in ft.xml_root.iterfind("FixtureType/DMXModes/DMXMode"):
        if m.get("Name") == mode_name:
            return m
    raise MoveError(f"mode « {mode_name} » introuvable")


def _attr(ch: ET.Element) -> str:
    lc = ch.find("LogicalChannel")
    return lc.get("Attribute", "") if lc is not None else ""


def _offsets(ch: ET.Element) -> list[int]:
    if ch.get("Offset") is None:  # MA3 : Coarse, Fine… (aucun = canal virtuel)
        return [int(ch.get(k)) for k in _BYTES if ch.get(k)]
    off = (ch.get("Offset") or "None").strip()
    return [] if off in ("None", "") else [int(o) for o in off.split(",")]


def _set_offsets(ft: FixtureType, ch: ET.Element, offsets: list[int]) -> None:
    if ft.format == "ma3":
        for k in _BYTES:
            ch.attrib.pop(k, None)
        for k, o in zip(_BYTES, offsets):
            ch.set(k, str(o))
    else:
        ch.set("Offset", ",".join(map(str, offsets)) if offsets else "None")


def _geo(ch: ET.Element) -> str:
    """Nom de la géométrie d'un canal (MA3 : dernier maillon du chemin pointé)."""
    return ch.get("Geometry", "").split(".")[-1]


def _find(mode_el: ET.Element, geo: str, attribute: str) -> ET.Element:
    for ch in mode_el.iterfind("DMXChannels/DMXChannel"):
        if _geo(ch) == geo and _attr(ch) == attribute:
            return ch
    raise MoveError(f"canal « {geo}_{attribute} » introuvable")


def lignes(ft: FixtureType, mode_name: str, g: Geometry) -> list[Ligne]:
    """Canaux de la géométrie (ou de son modèle) dans ce mode, dans l'ordre des adresses."""
    try:
        mode_el = _mode_el(ft, mode_name, read=True)
    except MoveError:
        return []
    geo = carrier(g)
    out = []
    for ch in mode_el.iterfind("DMXChannels/DMXChannel"):
        if _geo(ch) == geo:
            cf = ch.find("LogicalChannel/ChannelFunction")
            default = ch.get("Default") or (cf.get("Default", "") if cf is not None else "")
            out.append(Ligne(_attr(ch), _offsets(ch), default, geo))
    return sorted(out, key=lambda l: (not l.offsets, l.offsets[:1]))


def _space(ft: FixtureType, geo: str) -> set[str]:
    """Géométries qui partagent le même espace d'adresses : tout l'arbre (ou le modèle) de `geo`."""
    g = ft.geometry(geo)
    top = g
    while top is not None and top.parent is not None:
        top = top.parent
    return {x.name for x in top.walk()} if top is not None else {geo}


def _check_free(ft: FixtureType, mode_el: ET.Element, geo: str, offsets: list[int],
                skip: Optional[ET.Element] = None, dmx_break: str = "1") -> None:
    if any(not 1 <= o <= 512 for o in offsets) or len(set(offsets)) != len(offsets):
        raise MoveError("adresses hors de 1…512 ou répétées")
    names = _space(ft, geo)
    for ch in mode_el.iterfind("DMXChannels/DMXChannel"):
        if ch is skip or _geo(ch) not in names or ch.get("DMXBreak", "1") != dmx_break:
            continue
        clash = set(offsets) & set(_offsets(ch))
        if clash:
            raise MoveError(f"l'adresse {min(clash)} est déjà prise par « {_geo(ch)}_{_attr(ch)} »")


def _ensure_attribute(ft: FixtureType, name: str) -> None:
    """L'attribut doit être défini dans le fixture (avec sa feature), sinon fichier invalide."""
    from .creation import _definition
    node = ft.xml_root.find("FixtureType")
    attrs = node.find("AttributeDefinitions/Attributes")
    if attrs is None:
        raise MoveError("fixture sans définitions d'attributs")
    if any(a.get("Name") == name for a in attrs):
        return
    d = _definition(name)
    ET.SubElement(attrs, "Attribute", d)
    remap._ensure_groups(node, d.get("Feature", ""), d.get("ActivationGroup", ""))


def _done(ft: FixtureType, message: str) -> tuple[FixtureType, str]:
    return geotree.restore(ft, ET.tostring(ft.xml_root, encoding="utf-8")), message


def modifier(ft: FixtureType, mode_name: str, geo: str, attribute: str,
             offsets: Optional[list[int]] = None, new_attribute: Optional[str] = None,
             default: Optional[str] = None) -> tuple[FixtureType, str]:
    """Corrige un canal : adresses (coarse, fine…), attribut, valeur par défaut."""
    mode_el = _mode_el(ft, mode_name)
    ch = _find(mode_el, geo, attribute)
    done = []
    new = (new_attribute or "").strip()
    if new and new != attribute:
        if "." in new or " " in new:
            raise MoveError(f"nom d'attribut « {new} » : ni point ni espace")
        if any(c is not ch and _geo(c) == geo and _attr(c) == new
               for c in mode_el.iterfind("DMXChannels/DMXChannel")):
            raise MoveError(f"« {geo} » porte déjà l'attribut « {new} » dans ce mode")
    if offsets is not None and offsets != _offsets(ch):
        _check_free(ft, mode_el, geo, offsets, ch, ch.get("DMXBreak", "1"))
    if default is not None:
        default = _default_for(ft, default, not (offsets if offsets is not None else _offsets(ch)))

    if offsets is not None and offsets != _offsets(ch):
        _set_offsets(ft, ch, offsets)
        done.append("adresse " + ("/".join(map(str, offsets)) if offsets else "virtuelle"))
    if default is not None:
        cf = ch.find("LogicalChannel/ChannelFunction")
        if cf is not None and cf.get("Default") != default:
            cf.set("Default", default)
            done.append(f"défaut {default}")
    if new and new != attribute:
        _ensure_attribute(ft, new)
        lc = ch.find("LogicalChannel")
        lc.set("Attribute", new)
        for cf in lc.iterfind("ChannelFunction"):
            if cf.get("Attribute") == attribute:
                cf.set("Attribute", new)
            if cf.get("Name", "").startswith(attribute):
                cf.set("Name", new + cf.get("Name")[len(attribute):])
        dcf = ch.get("DefaultChannelFunction", "")  # MA3 : « Attribut.Fonction »
        if dcf.split(".")[0] == attribute:
            func = dcf.split(".", 1)[1] if "." in dcf else attribute
            ch.set("DefaultChannelFunction", f"{new}.{new + func[len(attribute):] if func.startswith(attribute) else func}")
        old_name, new_name = f"{geo}_{attribute}", f"{geo}_{new}"
        for el in mode_el.iter():  # liens vers ce canal : relations, InitialFunction, ModeMaster…
            for key in remap.LINK_ATTRS:
                v = el.get(key)
                if v and v.split(".")[0] == old_name:
                    segs = v.split(".")
                    segs[0] = new_name
                    if len(segs) > 1 and segs[1] == attribute:
                        segs[1] = new
                    if len(segs) > 2 and segs[2].startswith(attribute):
                        segs[2] = new + segs[2][len(attribute):]
                    el.set(key, ".".join(segs))
        done.append(f"attribut {attribute} → {new}")
    if not done:
        return ft, "rien à changer"
    return _done(ft, f"« {geo}_{new or attribute} » : " + ", ".join(done))


def _valid_dmx(value: str) -> bool:
    parts = value.split("/")
    return len(parts) == 2 and all(p.isdigit() for p in parts) and 1 <= int(parts[1]) <= 4


def _default_for(ft: FixtureType, value: str, virtual: bool) -> str:
    """Valeur par défaut au format du fichier. GDTF : « 128/1 ». MA3 : 24 bits en hexadécimal
    (« 80007F ») ; on accepte aussi « 128/1 », converti comme le fait l'export."""
    import re
    value = value.strip()
    if ft.format == "ma3":
        if re.fullmatch(r"[0-9A-Fa-f]{6}", value):
            return value.upper()
        if _valid_dmx(value):
            from .ma3xml import dmx_value
            return dmx_value(value, virtual)
        raise MoveError(f"valeur par défaut « {value} » : attendu 6 chiffres hexa (ex. 80007F) ou 128/1")
    if not _valid_dmx(value):
        raise MoveError(f"valeur par défaut « {value} » : attendu valeur/octets, ex. 128/1")
    return value


def ajouter(ft: FixtureType, mode_name: str, geo: str, attribute: str,
            offsets: list[int]) -> tuple[FixtureType, str]:
    """Ajoute un canal à la géométrie, avec une fonction sur toute la plage."""
    mode_el = _mode_el(ft, mode_name)
    attribute = attribute.strip()
    if not attribute or "." in attribute or " " in attribute:
        raise MoveError("il faut un nom d'attribut, sans point ni espace")
    if ft.geometry(geo) is None:
        raise MoveError(f"géométrie « {geo} » introuvable")
    chans = mode_el.find("DMXChannels")
    if chans is None:
        chans = ET.SubElement(mode_el, "DMXChannels")
    if any(_geo(c) == geo and _attr(c) == attribute for c in chans):
        raise MoveError(f"« {geo} » porte déjà l'attribut « {attribute} » dans ce mode")
    _check_free(ft, mode_el, geo, offsets)
    _ensure_attribute(ft, attribute)
    if ft.format == "ma3":  # forme d'un canal écrit par la console
        attrs = {k: str(o) for k, o in zip(_BYTES, offsets)}
        attrs["DefaultChannelFunction"] = f"{attribute}.{attribute} 1"
        attrs["Geometry"] = ".".join(geotree.names_path(ft.geometry(geo)))
        ch = ET.SubElement(chans, "DMXChannel", attrs)
        lc = ET.SubElement(ch, "LogicalChannel", {"Attribute": attribute})
        ET.SubElement(lc, "ChannelFunction", {"Name": f"{attribute} 1", "Attribute": attribute,
                                              "Default": "000000"})
        where = "/".join(map(str, offsets)) if offsets else "virtuel"
        return _done(ft, f"canal « {geo}_{attribute} » ajouté ({where})")
    n = max(1, len(offsets))
    ch = ET.SubElement(chans, "DMXChannel", {
        "DMXBreak": "1", "Offset": ",".join(map(str, offsets)) if offsets else "None",
        "InitialFunction": f"{geo}_{attribute}.{attribute}.{attribute} 1", "Highlight": "None",
        "Geometry": geo})
    lc = ET.SubElement(ch, "LogicalChannel", {"Attribute": attribute, "Snap": "No", "Master": "None"})
    ET.SubElement(lc, "ChannelFunction", {"Name": f"{attribute} 1", "Attribute": attribute,
                                          "DMXFrom": f"0/{n}", "Default": f"0/{n}",
                                          "PhysicalFrom": "0", "PhysicalTo": "1"})
    where = "/".join(map(str, offsets)) if offsets else "virtuel"
    return _done(ft, f"canal « {geo}_{attribute} » ajouté ({where})")


def retirer(ft: FixtureType, mode_name: str, geo: str, attribute: str) -> tuple[FixtureType, str]:
    """Retire un canal, et les relations qui pointaient dessus."""
    mode_el = _mode_el(ft, mode_name)
    ch = _find(mode_el, geo, attribute)
    name = f"{geo}_{attribute}"
    mode_el.find("DMXChannels").remove(ch)
    rel = mode_el.find("Relations")
    gone = 0
    if rel is not None:
        for r in list(rel):
            if name in (r.get("Master", "").split(".")[0], r.get("Follower", "").split(".")[0]):
                rel.remove(r)
                gone += 1
    for el in mode_el.iter():  # un ModeMaster qui dépendait de ce canal n'a plus de sens
        if el.get("ModeMaster", "").split(".")[0] == name:
            for k in ("ModeMaster", "ModeFrom", "ModeTo"):
                el.attrib.pop(k, None)
    return _done(ft, f"canal « {name} » retiré" + (f", {gone} relation(s) avec lui" if gone else ""))


def libre(ft: FixtureType, mode_name: str, geo: str) -> int:
    """Première adresse libre après les canaux de l'arbre de `geo` (pour « + Canal »)."""
    mode_el = _mode_el(ft, mode_name)
    names = _space(ft, geo)
    used = [o for ch in mode_el.iterfind("DMXChannels/DMXChannel") if _geo(ch) in names
            for o in _offsets(ch)]
    return min(512, max(used, default=0) + 1)


def attributs_connus(ft: FixtureType) -> list[str]:
    """Attributs proposés : ceux du fixture d'abord, puis ceux que la console connaît."""
    mine = [a.get("Name", "") for a in ft.xml_root.iterfind("FixtureType/AttributeDefinitions/Attributes/Attribute")]
    known = sorted(attributs._table("ma3_attributes.json"))
    return mine + [k for k in known if k not in mine]
