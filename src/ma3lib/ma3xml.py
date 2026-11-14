"""Écriture d'un fixture type au format XML grandMA3 2.3.2.0 (étape 4).

- Source MA3 (XML déjà exporté par la console, éventuellement retravaillé dans l'atelier) :
  on réécrit l'arbre d'origine tel quel, avec le nom / GUID demandés.
- Source GDTF : conversion GDTF 1.2 -> XML MA3, apprise sur les paires de Jo
  (GDTF Share + export console 2.3.2.0 : iTetra2, Esprite, Color Strike M, JDC Line 1000).
  Les règles sont listées dans docs/ma3-xml-notes.md (« Conversion GDTF -> MA3 »).

Ce que la console recalcule elle-même (grille Auto, index des médias dans le show) n'est
pas écrit. Les éléments inconnus sont recopiés tels quels plutôt que perdus.
"""

from __future__ import annotations

import base64
import io
import math
import re
import struct
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import xml.etree.ElementTree as ET

from . import attributs
from .gdtf import GEOMETRY_TAGS, FixtureType

DATA_VERSION = "2.3.2.0"
BLOCK = 1024  # octets par <Block Base64> dans les exports console

WHITE = "1.0000000000,1.0000000000,1.0000000000,1.0000000000"
BLACK = "0.0000000000,0.0000000000,0.0000000000,1.0000000000"

# Maillages génériques de la librairie console (Guid et index vus dans les exports de Jo).
GENERIC_MESHES = {
    "Cube": ("cube", "BD 38 A3 0B 49 67 10 0A 64 4C 12 51 B0 01 D8 1D", 1),
    "Cylinder": ("cylinder", "0D 49 20 00 37 A8 90 38 82 D8 B0 02 36 DD A0 ED", 3),
    "Pigtail": ("pigtail", "00 05 9A 3C 8B 5A 00 00 A8 98 1E 38 12 3B 91 19", 9),
}
GENERIC_MATERIAL = "A0 67 44 59 7B BF 10 06 91 F1 C6 AE 2F 45 18 E0"


class ExportError(Exception):
    pass


# --------------------------------------------------------------------------
# Petits formats
# --------------------------------------------------------------------------

def guid_ma3(guid: str) -> str:
    """« 704BDFBC-AE71-… » -> « 70 4B DF BC AE 71 … »."""
    h = re.sub(r"[^0-9A-Fa-f]", "", guid).upper()
    if len(h) != 32:
        h = uuid.uuid4().hex.upper()
    return " ".join(h[i:i + 2] for i in range(0, 32, 2))


def new_guid() -> str:
    return guid_ma3(uuid.uuid4().hex)


def _stable_guid(seed: str) -> str:
    return guid_ma3(uuid.uuid5(uuid.NAMESPACE_URL, seed).hex)


def dmx_value(value: Optional[str], virtual: bool = False) -> str:
    """Valeur DMX GDTF « 32768/2 » -> MA3 sur 24 bits « 80007F » (règle vérifiée sur la console :
    v * FFFFFF / (2^(8n) - 1), arrondi par défaut). Canal virtuel : la console passe par un
    pourcentage à 2 décimales (655/2 = 1,00 % -> 028F5C)."""
    if not value:
        return "000000"
    try:
        v, n = value.split("/")
        v, n = int(v), int(n)
    except ValueError:
        return "000000"
    top = (1 << (8 * n)) - 1
    v = max(0, min(v, top))
    if virtual:
        return f"{int(round(v / top, 4) * 0xFFFFFF):06X}"
    return f"{v * 0xFFFFFF // top:06X}"


def _f32(x: float) -> float:
    """La console calcule en flottants 32 bits (CosPhi 0.98 -> 0.9800000191)."""
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except OverflowError:
        return x


def _f(value: Optional[str], digits: int, default: float = 0.0, f32: bool = False) -> str:
    try:
        x = float(value) if value not in (None, "") else default
    except ValueError:
        x = default
    if f32:
        x = _f32(x)
    s = f"{x:.{digits}f}"
    return "0." + "0" * digits if s.startswith("-") and float(s) == 0 else s


def _num(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


# CIE xyY -> RGB linéaire. Matrice ajustée sur 180 couleurs de roues et filtres exportées
# par la console (le blanc D65 0.3127,0.3290,100 donne 0.99984,1.00002,1.00024).
_XYZ_RGB = ((3.2404542, -1.5371385, -0.4985314),
            (-0.9692660, 1.8760108, 0.0415560),
            (0.0556434, -0.2040259, 1.0572252))


def color_ma3(xyY: Optional[str]) -> str:
    try:
        x, y, Y = (float(v) for v in xyY.split(","))
    except (AttributeError, ValueError):
        return WHITE
    if y <= 0:
        return BLACK
    Y /= 100.0
    X, Z = x / y * Y, (1 - x - y) / y * Y
    rgb = [m[0] * X + m[1] * Y + m[2] * Z for m in _XYZ_RGB]
    return ",".join(f"{c:.10f}" for c in rgb) + ",1.0000000000"


def _date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return value


def _hexid(value: Optional[str]) -> str:
    v = (value or "").strip()
    return v[2:].upper() if v.lower().startswith("0x") else v


def _matrix(pos: Optional[str]) -> Optional[list[list[float]]]:
    rows = re.findall(r"\{([^}]*)\}", pos or "")
    if len(rows) < 3:
        return None
    try:
        return [[float(v) for v in r.split(",")] for r in rows]
    except ValueError:
        return None


def _position_attrs(pos: Optional[str]) -> dict[str, str]:
    """Matrice GDTF -> PosX/PosY/PosZ (et RotX/RotY/RotZ en degrés si la géométrie tourne)."""
    m = _matrix(pos)
    if not m:
        return {}
    out = {}
    for axis, i in (("X", 0), ("Y", 1), ("Z", 2)):
        v = m[i][3] if len(m[i]) > 3 else 0.0
        if abs(v) >= 0.00005:
            out[f"Pos{axis}"] = _f(str(v), 4)
    r = [row[:3] for row in m[:3]]
    if any(abs(r[i][j] - (1.0 if i == j else 0.0)) > 1e-6 for i in range(3) for j in range(3)):
        # matrice de rotation -> angles XYZ (convention Rz·Ry·Rx)
        ry = math.degrees(math.asin(max(-1.0, min(1.0, -r[2][0]))))
        rx = math.degrees(math.atan2(r[2][1], r[2][2]))
        rz = math.degrees(math.atan2(r[1][0], r[0][0]))
        for axis, v in (("X", rx), ("Y", ry), ("Z", rz)):
            if abs(v) >= 0.005:
                out[f"Rot{axis}"] = _f(str(v), 2)
    return out


def _el(parent: Optional[ET.Element], tag: str, attrs: Optional[dict] = None) -> ET.Element:
    attrs = {k: v for k, v in (attrs or {}).items() if v is not None}
    return ET.SubElement(parent, tag, attrs) if parent is not None else ET.Element(tag, attrs)


# --------------------------------------------------------------------------
# Écriture du fichier
# --------------------------------------------------------------------------

def _indent(e: ET.Element, level: int = 0) -> None:
    pad = "\n" + "    " * level
    if len(e):
        if not (e.text or "").strip():
            e.text = pad + "    "
        for c in e:
            _indent(c, level + 1)
        if not (c.tail or "").strip():
            c.tail = pad
    if level and not (e.tail or "").strip():
        e.tail = pad


def dumps(root: ET.Element) -> bytes:
    """Même mise en forme que la console : BOM, en-tête UTF-8, indentation 4 espaces."""
    root = _copy(root)
    for e in root.iter():
        e.tail = None if e is not root else None
        if len(e):
            e.text = None
    _indent(root)
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    body = re.sub(r'"/>', '" />', body).replace("&#13;", "&#xD;").replace("'", "&apos;")
    return ('﻿<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n").encode("utf-8")


def _copy(e: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(e))


def file_name(manufacturer: str, name: str) -> str:
    """Nom proposé par la console à l'export : « fabricant@nom.xml »."""
    raw = f"{manufacturer}@{name}.xml"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

class _Ctx:
    def __init__(self, ft: FixtureType, files: dict[str, bytes], name: str):
        self.ft = ft
        self.files = files
        self.name = name
        self.renames = _attribute_renames(ft)
        self.meshes_done: set[str] = set()
        src = ft.xml_root.find("FixtureType") if ft.xml_root is not None else None
        defs = _ma3_definitions()
        self.units: dict[str, str] = {}
        self.slots: dict[str, int] = {}
        if src is not None:
            for a in src.iterfind("AttributeDefinitions/Attributes/Attribute"):
                name = self.attr(a.get("Name", ""))
                known = defs.get(name)
                self.units[name] = (known or {}).get("PhysicalUnit", "") if known else a.get("PhysicalUnit", "")
            self.slots = {w.get("Name", ""): len(w.findall("Slot")) for w in src.iterfind("Wheels/Wheel")}

    def attr(self, name: Optional[str]) -> Optional[str]:
        return self.renames.get(name, name) if name is not None else None

    def link(self, text: Optional[str]) -> Optional[str]:
        """Renomme les attributs dans un lien (« Pixel_ColorAdd_R.ColorAdd_R.Red »)."""
        if not text:
            return text
        for old, new in self.renames.items():
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(old)}(?![A-Za-z0-9])", new, text)
        return text


def _attribute_renames(ft: FixtureType) -> dict[str, str]:
    """ColorAdd_R -> ColorRGB_R… sauf si le nom MA3 est déjà pris par un autre attribut.

    ColorSub_C et ColorAdd_R donnent tous deux ColorRGB_R : c'est permis tant qu'ils ne sont
    jamais ensemble sur la même géométrie d'un même mode (ex. un mode CMY et un mode RGB)."""
    names = set(ft.attributes)
    together: set[frozenset] = set()
    for mode in ft.modes:
        by_geo: dict[str, set[str]] = {}
        for ch in mode.channels:
            by_geo.setdefault(ch.geometry, set()).update(lc.attribute for lc in ch.logical_channels)
        for attrs in by_geo.values():
            together |= {frozenset((a, b)) for a in attrs for b in attrs if a != b}
    out: dict[str, str] = {}
    owner: dict[str, list[str]] = {n: [n] for n in names}
    for n in sorted(names):  # ordre fixe : ColorAdd_* avant ColorSub_*
        new = attributs.ma3_name(n)
        if new == n:
            continue
        others = owner.get(new, [])
        if others and (n not in attributs.GDTF_TO_MA3 or new in names
                       or any(frozenset((n, o)) in together for o in others)):
            continue
        out[n] = new
        owner.setdefault(new, []).append(n)
    return out


def _ma3_definitions() -> dict[str, dict]:
    import json
    path = attributs.DATA / "ma3_attribute_defs.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _attribute(ctx: _Ctx, a: ET.Element, parent: ET.Element, defs: dict) -> None:
    name = ctx.attr(a.get("Name", ""))
    known = defs.get(name)
    if known:  # la console remplace les attributs d'usine par sa propre définition
        _el(parent, "Attribute", dict(known))
        return
    pu = a.get("PhysicalUnit")
    _el(parent, "Attribute", {
        "Name": name, "Pretty": a.get("Pretty"), "ActivationGroup": a.get("ActivationGroup"),
        "MainAttribute": ctx.attr(a.get("MainAttribute")) or None, "Feature": a.get("Feature"),
        "SpecialIndex": "0", "PhysicalUnit": pu if pu and pu != "None" else None,
        "Color": color_ma3(a.get("Color")) if a.get("Color") else BLACK,
        "NaturalReadout": "Physical" if pu == "Angle" else "Percent",
        "EncoderResolution": "Coarse",
    })


def _attribute_definitions(ctx: _Ctx, src: ET.Element, out: ET.Element) -> None:
    ad = _el(out, "AttributeDefinitions")
    _el(ad, "DeactivationGroups")
    ags = _el(ad, "ActivationGroups")
    for g in src.iterfind("ActivationGroups/ActivationGroup"):
        _el(ags, "ActivationGroup", {"Name": g.get("Name")})
    fgs = _el(ad, "FeatureGroups")
    for fg in src.iterfind("FeatureGroups/FeatureGroup"):
        e = _el(fgs, "FeatureGroup", {"Name": fg.get("Name")})
        for f in fg.iterfind("Feature"):
            _el(e, "Feature", {"Name": f.get("Name")})
    attrs = _el(ad, "Attributes")
    defs = _ma3_definitions()
    done: set[Optional[str]] = set()
    for a in src.iterfind("Attributes/Attribute"):
        if ctx.attr(a.get("Name", "")) not in done:  # ColorSub_C et ColorAdd_R : un seul ColorRGB_R
            done.add(ctx.attr(a.get("Name", "")))
            _attribute(ctx, a, attrs, defs)


def _media_block(parent: ET.Element, data: bytes) -> None:
    fc = _el(parent, "FileContent", {"Size": str(max(1, math.ceil(len(data) / BLOCK)))})
    for i in range(0, len(data), BLOCK):
        _el(fc, "Block", {"Base64": base64.b64encode(data[i:i + BLOCK]).decode("ascii")})


def _dependency(parent: ET.Element, base: str, rel: str, num: Optional[int] = None) -> ET.Element:
    dep_root = _el(parent, "DependencyExport", {"Size": "1"})
    attrs = {"Base": base, "RelAddr": rel}
    if num is not None:
        attrs["RelAddrNum"] = str(num)
    attrs["Address"] = f"{base}.{rel}"
    if num is not None:
        attrs["AddressNum"] = f"14.7.{num}"
    return _el(dep_root, "Dependency", attrs)


def _find_file(files: dict[str, bytes], folder: str, stem: str, exts: tuple[str, ...]) -> Optional[str]:
    for ext in exts:
        for path in files:
            p = path.replace("\\", "/")
            if p.lower() == f"{folder}/{stem}.{ext}".lower() or (
                    p.lower().startswith(folder.lower() + "/") and p.rsplit("/", 1)[-1].lower() == f"{stem}.{ext}".lower()):
                return path
    return None


def _wheels(ctx: _Ctx, src: Optional[ET.Element], out: ET.Element) -> None:
    ws = _el(out, "Wheels")
    if src is None:
        return
    for w in src.iterfind("Wheel"):
        we = _el(ws, "Wheel", {"Name": w.get("Name")})
        for i, s in enumerate(w.iterfind("Slot")):
            attrs = {"Name": s.get("Name", ""), "Guid": _stable_guid(f"{ctx.name}/{w.get('Name')}/{i}"),
                     "Color": color_ma3(s.get("Color", "0.3127,0.3290,100"))}
            if s.get("Filter"):
                attrs["Filter"] = s.get("Filter")
            media = s.get("MediaFileName")
            if media:
                fname = f"{ctx.name}_{media}.png"
                attrs["MediaFileName"] = f"GOBO/{fname}"
            se = _el(we, "Slot", attrs)
            if media:
                # comme la console : la référence au média du pool Gobos, sans le contenu
                stem = f"[{ctx.name}_{media}_png]"
                dep = _dependency(se, "ShowData.MediaPools.Gobos", f"'{stem}'")
                gi = _el(dep, "GoboImage", {"Name": stem, "Guid": _stable_guid(f"{ctx.name}/gobo/{media}"),
                                            "FileName": f"{ctx.name}_{media}.png"})
                # image fournie avec le fixture (archive GDTF, section « Créer ») : contenu intégré comme
                # pour la vignette, sinon la console n'a rien à afficher pour un fixture qu'elle ne connaît pas
                path = _find_file(ctx.files, "wheels", media, ("png",))
                if path:
                    _media_block(gi, ctx.files[path])
            for facet in s.iterfind("Facet"):
                _el(se, "Facet", {"Color": color_ma3(facet.get("Color")), "Rotation": facet.get("Rotation")})
            for extra in s:
                if extra.tag not in ("Facet",):
                    se.append(_copy(extra))


def _measurement_points(m: ET.Element, out: ET.Element) -> None:
    for p in m.iterfind("MeasurementPoint"):
        attrs = {"WaveLength": _f(p.get("WaveLength"), 2)}
        energy = _f(p.get("Energy"), 3)
        if float(energy) != 0:
            attrs["Energy"] = energy
        _el(out, "MeasurementPoint", attrs)


def _physical(ctx: _Ctx, src: Optional[ET.Element], out: ET.Element) -> None:
    pd = _el(out, "PhysicalDescriptions")
    src = src if src is not None else ET.Element("PhysicalDescriptions")
    em = _el(pd, "Emitters")
    for e in src.iterfind("Emitters/Emitter"):
        attrs = {"Name": e.get("Name"), "Color": color_ma3(e.get("Color")) if e.get("Color") else None}
        if _num(e.get("DominantWaveLength")) != 0:
            attrs["DominantWaveLength"] = _f(e.get("DominantWaveLength"), 2)
        ee = _el(em, "Emitter", attrs)
        for m in e.iterfind("Measurement"):
            me = _el(ee, "MeasurementEmitter", {"LuminousIntensity": _f(m.get("LuminousIntensity"), 3)})
            _measurement_points(m, me)
    cris = _el(pd, "CRIs")
    for c in src.iterfind("CRIs/*"):
        cris.append(_copy(c))
    ff = _el(pd, "FTFilters")
    for f in src.iterfind("Filters/Filter"):
        fe = _el(ff, "FTFilter", {"Name": f.get("Name"), "Color": color_ma3(f.get("Color"))})
        for m in f.iterfind("Measurement"):
            me = _el(fe, "MeasurementFilter", {"Transmission": _f(m.get("Transmission"), 3)})
            _measurement_points(m, me)
    con = _el(pd, "Connectors")
    for c in src.iterfind("Connectors/*"):
        con.append(_copy(c))
    pp = _el(pd, "PhysicalProperties")
    props = src.find("Properties")
    if props is not None:
        t = props.find("OperatingTemperature")
        attrs = {}
        # valeurs par défaut de la console (non écrites) : 0 °C / 40 °C, 0 kg, 0 m
        if t is not None and _num(t.get("Low")) != 0:
            attrs["TempLow"] = _f(t.get("Low"), 2)
        if t is not None and _num(t.get("High"), 40) != 40:
            attrs["TempHigh"] = _f(t.get("High"), 2)
        w, lh = props.find("Weight"), props.find("LegHeight")
        if w is not None and _num(w.get("Value")) != 0:
            attrs["Weight"] = _f(w.get("Value"), 3)
        if lh is not None and _num(lh.get("Value")) != 0:
            attrs["LegHeight"] = _f(lh.get("Value"), 3)
        if attrs:
            _el(pp, "PhysicalPropertiesData", attrs)
    csc = _el(pd, "ColorSpaceCollect")
    cs = src.find("ColorSpace")
    if cs is not None and cs.get("Mode", "sRGB") == "Custom":
        _el(csc, "ColorSpaceData", {"ColorRed": color_ma3(cs.get("Red")), "ColorGreen": color_ma3(cs.get("Green")),
                                    "ColorBlue": color_ma3(cs.get("Blue")),
                                    "ColorWhitePoint": color_ma3(cs.get("WhitePoint"))})
    else:
        _el(csc, "ColorSpaceData", {"ColorRed": "1.0000000000,0.0000000000,0.0000000000,1.0000000000",
                                    "ColorGreen": "0.0000000000,1.0000000000,0.0000000000,1.0000000000",
                                    "ColorBlue": "0.0000000000,0.0000000000,1.0000000000,1.0000000000",
                                    "ColorWhitePoint": WHITE})
    _el(pd, "GamutCollect")


def _models(ctx: _Ctx, src: Optional[ET.Element], out: ET.Element) -> None:
    ms = _el(out, "Models")
    if src is None:
        return
    for m in src.iterfind("Model"):
        attrs = {"Name": m.get("Name"), "Length": _f(m.get("Length"), 4), "Width": _f(m.get("Width"), 4),
                 "Height": _f(m.get("Height"), 4), "DimensionsfollowRatio": "Yes", "CastShadow": "Yes"}
        stem = m.get("File") or ""
        mesh = None
        path = _find_file(ctx.files, "models/gltf", stem, ("glb",)) if stem else None
        path = path or (_find_file(ctx.files, "models/3ds", stem, ("3ds",)) if stem else None)
        if path:
            ext = path.rsplit(".", 1)[-1].lower()
            mesh = f"[{ctx.name}_{stem}_{ext}]"
            attrs["Mesh"] = mesh
            attrs["File"] = f"USERMESH/{ctx.name}_{stem}.{ext}"
        elif m.get("PrimitiveType") in GENERIC_MESHES:
            base, guid, num = GENERIC_MESHES[m.get("PrimitiveType")]
            mesh = f"[{base}_3ds]"
            attrs["Mesh"] = mesh
            attrs["File"] = f"MESH/gdtf_generic/{base}.3ds"
        me = _el(ms, "Model", attrs)
        if not mesh or mesh in ctx.meshes_done:
            continue
        ctx.meshes_done.add(mesh)
        if path:
            dep = _dependency(me, "ShowData.Meshes", f"'{mesh}'")
            um = _el(dep, "UserMesh", {"Name": mesh, "Guid": _stable_guid(f"{ctx.name}/mesh/{stem}"),
                                       "FileName": f"{ctx.name}_{stem}.{path.rsplit('.', 1)[-1].lower()}",
                                       "Culling": "No"})
            _media_block(um, ctx.files[path])
            _el(um, "UserMaterial", {"Name": "Material 1", "Guid": _stable_guid(f"{ctx.name}/mat/{stem}")})
        else:
            base, guid, num = GENERIC_MESHES[m.get("PrimitiveType")]
            dep = _dependency(me, "ShowData.Meshes", mesh, num)
            mse = _el(dep, "Mesh", {"Lock": "UL", "Name": mesh, "Guid": guid, "FileName": f"{base}.3ds",
                                    "FilePath": "gdtf_generic", "Culling": "No"})
            _el(mse, "Material", {"Name": "Material 1", "Guid": GENERIC_MATERIAL, "FilePath": "gdtf_generic"})


_BEAM_ORDER = (("PowerConsumption", 1), ("LuminousFlux", 1), ("ColorTemperature", 1), ("BeamAngle", 2),
               ("BeamRadius", 3), ("FieldAngle", 2), ("LampType", None), ("BeamType", None),
               ("ThrowRatio", 3), ("ColorRenderingIndex", None), ("EmitterSpectrum", None))
_DROP_GEOMETRY = {"Position", "Model", "Name", "Geometry", "RectangleRatio"}


def _geometry(ctx: _Ctx, g: ET.Element, parent: ET.Element) -> None:
    attrs: dict[str, Optional[str]] = {"Name": g.get("Name")}
    if g.tag != "GeometryReference" and g.get("Model"):
        attrs["Model"] = g.get("Model")
    attrs.update(_position_attrs(g.get("Position")))
    attrs["GridAuto"] = "Auto"
    if g.tag == "Beam":
        for key, digits in _BEAM_ORDER:
            v = g.get(key)
            if key == "ThrowRatio":
                # la console recalcule : 1 / (2 tan(BeamAngle / 2))
                angle = _num(g.get("BeamAngle"), 25.0)
                v = str(1 / (2 * math.tan(math.radians(angle) / 2))) if 0 < angle < 180 else v
            if key == "BeamType" and (v or "Wash") == "Wash":
                continue
            if key in ("BeamAngle", "FieldAngle") and _num(v, 25.0) == 25.0:  # défaut console
                continue
            if v is None:
                continue
            name = "LuminousIntensity" if key == "LuminousFlux" else key
            attrs[name] = _f(v, digits, f32=True) if digits is not None else (
                str(int(_num(v))) if key == "ColorRenderingIndex" else v)
    for k, v in g.attrib.items():  # le reste (Laser, Display, WiringObject…) est gardé tel quel
        if k not in attrs and k not in _DROP_GEOMETRY and not (g.tag == "Beam" and k in dict(_BEAM_ORDER)):
            if v == "":
                continue
            if re.fullmatch(r"-?\d+\.\d+", v):  # nombres : 10 décimales, en flottant 32 bits
                v = _f(v, 10, f32=True)
            attrs[k] = v
    if g.tag == "GeometryReference":
        attrs["Geometry"] = g.get("Geometry")
    e = _el(parent, g.tag, attrs)
    for c in g:
        if c.tag == "Break":
            b = {}
            if c.get("DMXOffset", "1") != "1":
                b["DMXPatch"] = c.get("DMXOffset")
            if c.get("DMXBreak", "1") != "1":
                b["DMXBreak"] = c.get("DMXBreak")
            _el(e, "Break", b)
        elif c.tag in GEOMETRY_TAGS:
            _geometry(ctx, c, e)
        else:
            e.append(_copy(c))


def _geometries(ctx: _Ctx, src: Optional[ET.Element], out: ET.Element) -> None:
    gs = _el(out, "Geometries")
    if src is None:
        return
    referenced = {r.get("Geometry") for r in src.iter("GeometryReference")}
    tops = list(src)
    # la console écrit d'abord les modèles de référence
    for g in sorted(tops, key=lambda x: x.get("Name") not in referenced):
        if g.tag in GEOMETRY_TAGS:
            _geometry(ctx, g, gs)


def _geometry_paths(src: Optional[ET.Element]) -> dict[str, str]:
    """Nom de géométrie -> chemin pointé MA3 (« Base.Head ») ; nom simple pour un modèle référencé."""
    out: dict[str, str] = {}
    if src is None:
        return out
    referenced = {r.get("Geometry") for r in src.iter("GeometryReference")}

    def walk(e: ET.Element, prefix: str) -> None:
        for c in e:
            if c.tag in GEOMETRY_TAGS:
                path = f"{prefix}.{c.get('Name')}" if prefix else c.get("Name", "")
                out.setdefault(c.get("Name", ""), path)
                walk(c, path)

    for top in src:
        if top.tag in GEOMETRY_TAGS:
            name = top.get("Name", "")
            out[name] = name
            walk(top, name)
    for r in referenced:
        if r in out:
            out[r] = r
    return out


_CF_PHYSICAL = 10


_dmx = dmx_value


def _subtractive(attr: Optional[str]) -> bool:
    return bool(attr) and attr in attributs.GDTF_TO_MA3


def _invert(value: str) -> str:
    return f"{0xFFFFFF - int(value, 16):06X}"


def _channel_function(ctx: _Ctx, cf: ET.Element, parent: ET.Element, virtual: bool = False) -> None:
    def dmx_value(v: Optional[str]) -> str:
        return _dmx(v, virtual)

    attrs: dict[str, Optional[str]] = {"Name": cf.get("Name"), "Attribute": ctx.attr(cf.get("Attribute"))}
    if cf.get("OriginalAttribute"):
        attrs["OriginalAttribute"] = cf.get("OriginalAttribute")
    frm = dmx_value(cf.get("DMXFrom"))
    if frm != "000000":
        attrs["DMXFrom"] = frm
    attrs["Default"] = dmx_value(cf.get("Default"))
    if _subtractive(cf.get("Attribute")):
        # ColorSub_C -> ColorRGB_R : la console inverse le canal (0 % cyan = 100 % rouge)
        attrs["DMXInvert"] = "Yes"
        attrs["Default"] = _invert(attrs["Default"])
    pf, pt = _num(cf.get("PhysicalFrom"), 0.0), _num(cf.get("PhysicalTo"), 1.0)
    unit = ctx.units.get(attrs["Attribute"] or "", "")
    scale = math.pi / 180 if unit == "AngularSpeed" else 1.0  # la console stocke des rad/s
    # physique absente du GDTF : valeurs d'usage de la console (0 à 1), sans conversion d'unité
    pf = pf * scale if cf.get("PhysicalFrom") is not None else pf
    pt = pt * scale if cf.get("PhysicalTo") is not None else pt
    if cf.get("Wheel") and unit in ("", "None"):
        # index de roue : la console compte en emplacements (0 … nombre de slots)
        pf, pt = 0.0, float(ctx.slots.get(cf.get("Wheel", ""), 1))
    if pf != 0.0:
        attrs["PhysicalFrom"] = _f(str(pf), _CF_PHYSICAL)
    if pt != 1.0:
        attrs["PhysicalTo"] = _f(str(pt), _CF_PHYSICAL)
    for key in ("RealFade", "RealAcceleration"):
        if _num(cf.get(key)) != 0:
            attrs[key] = _f(cf.get(key), 3)
    for key in ("Wheel", "Emitter", "Filter", "ModeMaster"):
        if cf.get(key):
            attrs[key] = ctx.link(cf.get(key))
    if cf.get("ModeMaster"):
        for key in ("ModeFrom", "ModeTo"):
            v = dmx_value(cf.get(key))
            if v != "000000":
                attrs[key] = v
    e = _el(parent, "ChannelFunction", attrs)
    for cs in cf.iterfind("ChannelSet"):
        sa: dict[str, Optional[str]] = {}
        if cs.get("Name"):
            sa["Name"] = cs.get("Name")
        v = dmx_value(cs.get("DMXFrom"))
        if v != "000000":
            sa["DMXFrom"] = v
        wsi = cs.get("WheelSlotIndex")
        if wsi not in (None, "0", "-2147483648"):
            sa["WheelSlotIndex"] = wsi
        if cs.get("PhysicalFrom") is not None or cs.get("PhysicalTo") is not None:
            cpf, cpt = _num(cs.get("PhysicalFrom"), 0.0) * scale, _num(cs.get("PhysicalTo"), 1.0) * scale
            if cpf != 0.0:
                sa["PhysicalFrom"] = _f(str(cpf), 4)
            if cpt != 1.0:
                sa["PhysicalTo"] = _f(str(cpt), 4)
            sa["HasPhysical"] = "Yes"
        elif "WheelSlotIndex" in sa and cf.get("Wheel") and unit in ("", "None"):
            # emplacement fixe, comme dans les exports de la console (Esprite) : physique 0 à 0, relative au
            # centre de l'emplacement. Sans elle, onPC 2.3.2.0 déduit l'emplacement en répartissant la plage
            # DMX de la fonction et l'image affichée est décalée (Jo, 13/11/2026).
            sa["PhysicalTo"] = "0.0000"
            sa["HasPhysical"] = "Yes"
        _el(e, "ChannelSet", sa)
    for sub in cf:
        if sub.tag != "ChannelSet":
            e.append(_copy(sub))


def _single_breaks(geos: Optional[ET.Element], root_name: str) -> dict[str, str]:
    """Géométries de modèle dont toutes les références (dans l'arbre du mode) n'ont qu'un Break :
    {nom: DMXBreak de ce Break}. Vu sur onPC 2.3.2.0 (iTetra2, 11/11/2026) : avec un seul Break,
    un canal en DMXBreak="Overwrite" ne prend pas l'adresse de la référence et tous les pixels
    tombent au même endroit. On écrit alors le numéro du Break."""
    if geos is None:
        return {}
    tops = {g.get("Name"): g for g in geos if g.tag in GEOMETRY_TAGS}
    seen: dict[str, set] = {}
    todo, done = [root_name], set()
    while todo:
        name = todo.pop()
        if name in done or name not in tops:
            continue
        done.add(name)
        for r in tops[name].iter("GeometryReference"):
            target = r.get("Geometry", "")
            brs = r.findall("Break")
            seen.setdefault(target, set()).add(brs[0].get("DMXBreak", "1") if len(brs) == 1 else None)
            todo.append(target)
    out: dict[str, str] = {}
    for target, kinds in seen.items():
        if len(kinds) == 1 and None not in kinds and target in tops:
            for g in tops[target].iter():
                if g.tag in GEOMETRY_TAGS:
                    out[g.get("Name", "")] = next(iter(kinds))
    return out


def _dmx_mode(ctx: _Ctx, m: ET.Element, paths: dict[str, str], out: ET.Element,
              personality: bool, geos: Optional[ET.Element] = None) -> None:
    single = _single_breaks(geos, m.get("Geometry", ""))
    me = _el(out, "DMXMode", {"Name": m.get("Name"), "Geometry": m.get("Geometry"), "XYZ": "No", "DiveInto": "Yes"})
    chs = _el(me, "DMXChannels")
    for ch in m.iterfind("DMXChannels/DMXChannel"):
        attrs: dict[str, Optional[str]] = {}
        offs = [o for o in (ch.get("Offset") or "").split(",") if o.strip() and o.strip() != "None"]
        for key, o in zip(("Coarse", "Fine", "Ultra", "Uber"), offs):
            attrs[key] = o.strip()
        brk = ch.get("DMXBreak", "1")
        if brk == "Overwrite" and ch.get("Geometry", "") in single:
            brk = single[ch.get("Geometry", "")]
        if brk not in ("1", ""):
            attrs["DMXBreak"] = brk
        init = ch.get("InitialFunction") or ""
        if init:
            attrs["DefaultChannelFunction"] = ctx.link(init.split(".", 1)[1] if "." in init else init)
        if ch.get("Highlight") not in (None, "", "None"):
            attrs["Highlight"] = dmx_value(ch.get("Highlight"), not offs)
            if any(_subtractive(lc.get("Attribute")) for lc in ch.iterfind("LogicalChannel")):
                attrs["Highlight"] = _invert(attrs["Highlight"])
        attrs["Geometry"] = paths.get(ch.get("Geometry", ""), ch.get("Geometry"))
        ce = _el(chs, "DMXChannel", attrs)
        for lc in ch.iterfind("LogicalChannel"):
            la: dict[str, Optional[str]] = {"Attribute": ctx.attr(lc.get("Attribute"))}
            if lc.get("Snap") not in (None, "No"):
                la["Snap"] = lc.get("Snap")
            if lc.get("Master") not in (None, "None"):
                la["Master"] = lc.get("Master")
            le = _el(ce, "LogicalChannel", la)
            for cf in lc.iterfind("ChannelFunction"):
                _channel_function(ctx, cf, le, virtual=not offs)
    rel = _el(me, "Relations")
    for r in m.iterfind("Relations/Relation"):
        _el(rel, "Relation", {"Name": r.get("Name"), "Master": ctx.link(r.get("Master")),
                              "Follower": ctx.link(r.get("Follower")), "Type": r.get("Type")})
    macros = _el(me, "FTMacros")
    for mac in m.iterfind("FTMacros/*"):
        macros.append(_copy(mac))
    sv = _el(me, "SoftwareVersions")
    if personality:
        _el(sv, "SoftwareVersion", {"SoftwareVersionID": "0"})
    _el(me, "FTPresets")


def _protocols(src: Optional[ET.Element], out: ET.Element) -> set[str]:
    """FTRDM -> RDMFixtureType. Renvoie les modes qui ont une personnalité RDM."""
    pr = _el(out, "Protocols")
    modes: set[str] = set()
    if src is None:
        return modes
    for rdm in src.iterfind("FTRDM"):
        r = _el(pr, "RDMFixtureType", {"ManufacturerID": _hexid(rdm.get("ManufacturerID")),
                                       "DeviceModelID": _hexid(rdm.get("DeviceModelID"))})
        _el(r, "Parameters")
        _el(_el(r, "Notifications"), "RDMAbsentNotification")
        coll = _el(r, "FTRDMPersonalityCollect")
        pers = list(rdm.iter("DMXPersonality"))
        modes |= {p.get("DMXMode", "") for p in pers}
        for p in pers:
            try:
                pid = str(int(_hexid(p.get("Value")) or "0", 16))
            except ValueError:
                pid = p.get("Value", "0")
            _el(coll, "Personality", {"PersonalityId": pid})
    for other in src:
        if other.tag != "FTRDM":
            pr.append(_copy(other))
    return modes


def _thumbnail(ctx: _Ctx, ft_el: ET.Element) -> Optional[bytes]:
    for name in ("thumbnail.png",):
        stem = ft_el.get("Thumbnail") or "thumbnail"
        for path in ctx.files:
            if path.lower() == f"{stem}.png".lower():
                return ctx.files[path]
        if name in ctx.files:
            return ctx.files[name]
    return None


def convert(ft: FixtureType, files: Optional[dict[str, bytes]] = None, name: Optional[str] = None,
            guid: Optional[str] = None, note: Optional[str] = None) -> ET.Element:
    """Arbre <GMA3> pour un fixture type GDTF (ou MA3 : copie de l'arbre, nom/GUID mis à jour)."""
    if ft.xml_root is None:
        raise ExportError("fixture sans arbre XML d'origine")
    if ft.format == "ma3":
        root = _copy(ft.xml_root)
        root.set("DataVersion", DATA_VERSION)
        node = root.find("FixtureType")
        if name:
            node.set("Name", name)
        if guid:
            node.set("Guid", guid_ma3(guid))
        if note:
            node.set("Note", note)
        elif note is not None:
            node.attrib.pop("Note", None)
        return root

    files = files if files is not None else read_files(ft.source)
    src = ft.xml_root.find("FixtureType")
    if src is None:
        raise ExportError("pas de <FixtureType>")
    # meshes ajoutés dans l'atelier : pris dans un autre GDTF, ou formes de la banque de l'appli
    from . import meshbank
    files = {**meshbank.files_for(m.get("File") or "" for m in src.iterfind("Models/Model")),
             **files, **ft.extra_files}
    name = name or src.get("Name", ft.name)
    ctx = _Ctx(ft, files, name)
    root = ET.Element("GMA3", {"DataVersion": DATA_VERSION})
    thumb = _thumbnail(ctx, src)
    head: dict[str, Optional[str]] = {"Name": name, "Guid": guid_ma3(guid or src.get("FixtureTypeID", "")),
                                      "Note": note or None, "Color": WHITE}
    if thumb:
        head["MediaFileName"] = f"USERSYMBOL/{name}_thumbnail.png"
    for key in ("ShortName", "LongName", "Description", "Manufacturer"):
        v = src.get(key, "")
        head[key] = v.strip().replace("\r\n", "\r").replace("\n", "\r") if key != "Manufacturer" else v
    head["Universal"] = "No"
    head["CanHaveChildren"] = src.get("CanHaveChildren", "Yes")
    fte = _el(root, "FixtureType", head)
    if thumb:
        stem = f"[{name}_thumbnail_png]"
        dep = _dependency(fte, "ShowData.MediaPools.Symbols", f"'{stem}'")
        dep.attrib.pop("Base", None)
        dep.set("RelAddr", dep.get("Address"))
        si = _el(dep, "SymbolImage", {"Name": stem, "Guid": _stable_guid(f"{name}/thumbnail"),
                                      "FileName": f"{name}_thumbnail.png"})
        _media_block(si, thumb)

    ad = src.find("AttributeDefinitions")
    _attribute_definitions(ctx, ad if ad is not None else ET.Element("AttributeDefinitions"), fte)
    _wheels(ctx, src.find("Wheels"), fte)
    _physical(ctx, src.find("PhysicalDescriptions"), fte)
    _models(ctx, src.find("Models"), fte)
    _geometries(ctx, src.find("Geometries"), fte)
    paths = _geometry_paths(src.find("Geometries"))
    pr_tmp = ET.Element("tmp")
    with_personality = _protocols(src.find("Protocols"), pr_tmp)
    modes = _el(fte, "DMXModes")
    for m in src.iterfind("DMXModes/DMXMode"):
        _dmx_mode(ctx, m, paths, modes, m.get("Name") in with_personality, src.find("Geometries"))
    revs = _el(fte, "Revisions")
    for r in src.iterfind("Revisions/Revision"):
        _el(revs, "Revision", {"Text": r.get("Text") or None, "Date": _date(r.get("Date", "")),
                               "UserID": r.get("UserID", "0"), "ModifiedBy": r.get("ModifiedBy") or None})
    fte.extend(list(pr_tmp))
    return root


def read_files(source: Optional[Path]) -> dict[str, bytes]:
    """Fichiers d'une archive GDTF (maillages, roues, vignette)."""
    if source is None or not zipfile.is_zipfile(source):
        return {}
    with zipfile.ZipFile(source) as zf:
        return {n: zf.read(n) for n in zf.namelist() if n != "description.xml" and not n.endswith("/")}


def export(ft: FixtureType, folder: Path, name: Optional[str] = None, guid: Optional[str] = None,
           note: Optional[str] = None, overwrite: bool = False) -> Path:
    """Écrit « fabricant@nom.xml » dans `folder` et renvoie le chemin."""
    root = convert(ft, name=name, guid=guid, note=note)
    node = root.find("FixtureType")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / file_name(node.get("Manufacturer", ft.manufacturer), node.get("Name", ft.name))
    if dest.exists() and not overwrite:
        raise FileExistsError(str(dest))
    dest.write_bytes(dumps(root))
    return dest
