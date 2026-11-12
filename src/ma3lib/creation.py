"""Créer un fixture type de zéro (étape 5, Jo, 11/11/2026).

Deux entrées possibles, qui remplissent le même `Projet` :
- la charte DMX d'une notice PDF (voir `pdfchart.py`) ;
- la saisie à la main (modes, canaux, adresses, géométries).

`construire()` en fait un vrai `FixtureType` GDTF en mémoire (avec son arbre XML), que
l'atelier sait ensuite retravailler et exporter en XML MA3 : on ne réinvente rien en aval.

Géométries : par défaut Base > Yoke (Pan) > Head (Tilt et le reste). Une géométrie nommée avec
« copies » > 1 (pixels, têtes…) devient un modèle + N références aux adresses contiguës
(règle de Jo). Dès qu'il y a des copies et plusieurs modes, chaque mode reçoit sa base.
"""

from __future__ import annotations

import json
import re
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

from . import APP_NAME, attributs, gdtf
from .gdtf import FixtureType

BASE, YOKE, HEAD = "Base", "Yoke", "Head"


class CreationError(Exception):
    """Le projet ne peut pas devenir un fixture (message lisible par Jo)."""


@dataclass
class Plage:
    debut: int
    fin: int
    nom: str


@dataclass
class Canal:
    adresse: int
    fine: Optional[int] = None
    nom: str = ""  # texte de la notice
    attribut: str = ""  # attribut GDTF / MA3 ; vide = à deviner
    geometrie: str = ""  # vide = Yoke pour Pan, Head pour le reste
    copies: int = 1  # > 1 : la géométrie devient un modèle + N références
    defaut: int = 0
    plages: list[Plage] = field(default_factory=list)

    @property
    def adresses(self) -> list[int]:
        return [self.adresse] + ([self.fine] if self.fine else [])


@dataclass
class Mode:
    nom: str
    canaux: list[Canal] = field(default_factory=list)

    @property
    def empreinte(self) -> int:
        """Nombre d'adresses DMX occupées, copies comprises."""
        last = 0
        for geo, canaux in _par_geometrie(self).items():
            first = min(a for c in canaux for a in c.adresses)
            end = max(a for c in canaux for a in c.adresses)
            n = max(c.copies for c in canaux) if geo else 1
            last = max(last, first + (end - first + 1) * n - 1)
        return last


@dataclass
class Projet:
    fabricant: str = ""
    nom: str = ""
    court: str = ""
    modes: list[Mode] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # remarques de la lecture du PDF

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "Projet":
        d = json.loads(text)
        modes = [Mode(m["nom"], [Canal(**{**c, "plages": [Plage(**p) for p in c.get("plages", [])]})
                                 for c in m.get("canaux", [])]) for m in d.get("modes", [])]
        return cls(d.get("fabricant", ""), d.get("nom", ""), d.get("court", ""), modes, d.get("notes", []))


def _par_geometrie(mode: Mode) -> dict[str, list[Canal]]:
    """Canaux regroupés par géométrie nommée à copies ('' = le corps du fixture)."""
    out: dict[str, list[Canal]] = {}
    for c in mode.canaux:
        out.setdefault(c.geometrie if c.copies > 1 and c.geometrie else "", []).append(c)
    return out


# --------------------------------------------------------------------------
# Du texte de la notice à l'attribut
# --------------------------------------------------------------------------

# Ordre important : du plus précis au plus vague.
_RULES: list[tuple[str, str]] = [
    (r"reserved|not used|unused|no function|réservé", "NoFeature"),
    (r"(pan|p)\s*/\s*(tilt|t).*(speed|time)|(speed|time).*(pan|movement)", "PositionMSpeed"),
    (r"\bpan\b.*(rot|continu)", "PanRotate"),
    (r"\btilt\b.*(rot|continu)", "TiltRotate"),
    (r"\bpan\b", "Pan"),
    (r"\btilt\b", "Tilt"),
    (r"dimmer curve", "DimmerCurve"),
    (r"dimmer (mode|speed)", "DimmerMode"),
    (r"strobe.*(duration|length)", "StrobeDuration"),
    (r"shutter|strobe", "Shutter1"),
    (r"x-?fade|cross-?fade", ""),  # propre au fabricant : attribut maison
    (r"blade\s*(\d).*(swivel|rot|angle)", r"Blade\1Rot"),
    (r"blade\s*(\d)", r"Blade\1A"),
    (r"(frame|shaper|shutter|blade)s?.*macros? speed", "ShaperMacrosSpeed"),
    (r"(frame|shaper|blade)s?.*macro", "ShaperMacros"),
    (r"(frame|shaper|blade|framing)s?.*rot", "ShaperRot"),
    (r"(ovali[sz]er|beam ?shaper).*(index|rot)", "BeamShaperPos"),
    (r"ovali[sz]er|beam ?shaper", "BeamShaper"),
    (r"gobo\s*(\d)?.*(index|rot)", r"Gobo\1Pos"),
    (r"gobo\s*(\d)?", r"Gobo\1"),
    (r"prism\s*(\d)?.*(index|rot)", r"Prism\1Pos"),
    (r"prism\s*(\d)?", r"Prism\1"),
    (r"animation.*(index|rot)", "AnimationWheel1Pos"),
    (r"animation", "AnimationWheel1"),
    (r"frost\s*(\d)?", r"Frost\1"),
    (r"\biris\b", "Iris"),
    (r"\bzoom\b", "Zoom"),
    (r"\bfocus\b", "Focus1"),
    (r"\bcto\b", "CTO"),
    (r"\bctb\b", "CTB"),
    (r"\bcct\b|\bctc\b|colou?r temp", "CTC"),
    (r"\bgmp\b|\btint\b|green.{0,3}magenta|(minus|plus) green", "Tint"),
    (r"\bcri\b", "CRIMode"),
    (r"virtual colou?r|colou?r (macro|preset)|\bgel\b", "ColorMacro1"),
    (r"colou?r wheel|^colou?r( \d)?$", "Color1"),
    (r"warm white|\bww\b", "ColorAdd_WW"),
    (r"co(ol|ld) white|\bcw\b", "ColorAdd_CW"),
    (r"\bred\b", "ColorAdd_R"),
    (r"\bgreen\b", "ColorAdd_G"),
    (r"\bblue\b", "ColorAdd_B"),
    (r"\bwhite\b", "ColorAdd_W"),
    (r"\bamber\b", "ColorAdd_RY"),
    (r"\blime\b", "ColorAdd_GY"),
    (r"\buv\b|ultra ?violet", "ColorAdd_UV"),
    (r"\bcyan\b", "ColorSub_C"),
    (r"\bmagenta\b", "ColorSub_M"),
    (r"\byellow\b", "ColorSub_Y"),
    (r"^x$", "CIE_X"),
    (r"^y$", "CIE_Y"),
    (r"\bhue\b", "HSB_Hue"),
    (r"\bsaturation\b", "HSB_Saturation"),
    (r"\bpwm\b|led freq", "LEDFrequency"),
    (r"\bfans?\b", "Fans"),
    (r"control|function|reset|settings|lamp", "Control1"),
    (r"(effect|macro|program|chase|pattern).*(speed|rate)", "Effects1Rate"),
    (r"effect|macro|program|chase|pattern", "Effects1"),
    (r"dimmer|intensity|master", "Dimmer"),
]
_COMPILED = [(re.compile(rx, re.I), attr) for rx, attr in _RULES]
_FINE = re.compile(r"\bfine\b|\blsb\b|16 ?bits? low", re.I)


def est_fine(nom: str) -> bool:
    return bool(_FINE.search(nom))


def nom_maison(nom: str) -> str:
    """Nom d'attribut maison tiré du texte de la notice (« XFade CTC>COLOR » -> XFadeCTCCOLOR)."""
    words = re.findall(r"[A-Za-z0-9]+", nom)
    out = "".join(w[:1].upper() + w[1:] for w in words)
    return ("A" + out if out[:1].isdigit() else out) or "Canal"


def deviner(nom: str, voisins: Optional[list[str]] = None) -> str:
    """Attribut probable pour le nom d'un canal de la notice (« Blade 2 swivelling » -> Blade2Rot).

    `voisins` : les autres noms du mode. Cyan/Magenta/Yellow sont soustractifs (CMY) sauf si le
    mode a aussi Rouge, Vert et Bleu : ce sont alors des émetteurs LED de plus."""
    text = re.sub(r"\s+", " ", nom).strip()
    for rx, attr in _COMPILED:
        m = rx.search(text)
        if not m:
            continue
        if not attr:
            break
        attr = m.expand(attr) if "\\" in attr else attr
        attr = re.sub(r"^(Gobo|Prism|Frost)(?=Pos|$)", r"\g<1>1", attr)
        if attr.startswith("ColorSub_") and voisins is not None:
            others = " ".join(voisins).lower()
            if all(w in others for w in ("red", "green", "blue")):
                attr = attr.replace("ColorSub_", "ColorAdd_")
        return attr
    return nom_maison(text)


def _suivant(attr: str, pris: set[str]) -> str:
    """Deuxième canal du même attribut sur la même géométrie : Control1 -> Control2, sinon suffixe."""
    m = re.match(r"^(.*?)(\d+)(\D*)$", attr)
    n = int(m.group(2)) if m else 1
    while True:
        n += 1
        cand = f"{m.group(1)}{n}{m.group(3)}" if m else f"{attr}{n}"
        if cand not in pris:
            return cand


def attribuer(mode: Mode, force: bool = False) -> None:
    """Remplit les attributs vides du mode (tous si `force`), sans doublon par géométrie."""
    noms = [c.nom for c in mode.canaux]
    pris: dict[str, set[str]] = {}
    for c in mode.canaux:
        if c.attribut and not force:
            pris.setdefault(c.geometrie, set()).add(c.attribut)
    for c in mode.canaux:
        if c.attribut and not force:
            continue
        attr = deviner(c.nom, noms)
        used = pris.setdefault(c.geometrie, set())
        if attr in used:
            # famille numérotée (ColorMacro1, Control1…) : le suivant ; sinon un attribut maison
            numbered = bool(re.search(r"\d$", attr))
            attr = _suivant(attr, used) if numbered or nom_maison(c.nom) in used else nom_maison(c.nom)
        used.add(attr)
        c.attribut = attr


# --------------------------------------------------------------------------
# Contrôles
# --------------------------------------------------------------------------

def verifier(projet: Projet) -> list[str]:
    """Problèmes qui empêchent de créer le fixture (liste vide = tout va bien)."""
    out: list[str] = []
    if not projet.nom.strip():
        out.append("Il manque le nom du fixture.")
    if not projet.modes:
        out.append("Il faut au moins un mode.")
    seen_modes: set[str] = set()
    for mode in projet.modes:
        if not mode.nom.strip() or mode.nom in seen_modes:
            out.append(f"Nom de mode vide ou en double : « {mode.nom} ».")
        seen_modes.add(mode.nom)
        if not mode.canaux:
            out.append(f"{mode.nom} : aucun canal.")
        used: dict[int, str] = {}
        names: set[tuple[str, str]] = set()
        for geo, canaux in _par_geometrie(mode).items():
            first = min(a for c in canaux for a in c.adresses)
            span = max(a for c in canaux for a in c.adresses) - first + 1
            n = max(c.copies for c in canaux) if geo else 1
            for c in canaux:
                label = c.nom or c.attribut or f"canal {c.adresse}"
                if c.adresse < 1 or (c.fine is not None and c.fine < 1):
                    out.append(f"{mode.nom} : adresse invalide pour « {label} ».")
                if not c.attribut:
                    out.append(f"{mode.nom} : « {label} » n'a pas d'attribut.")
                key = (_geo_name(c), c.attribut)
                if c.attribut and key in names:
                    out.append(f"{mode.nom} : deux canaux « {c.attribut} » sur la géométrie {key[0]}.")
                names.add(key)
                for k in range(n):
                    for a in c.adresses:
                        addr = a + k * span
                        if addr in used:
                            out.append(f"{mode.nom} : l'adresse {addr} sert à « {used[addr]} » et à « {label} ».")
                        used[addr] = label
        if used and (missing := [a for a in range(1, max(used) + 1) if a not in used]):
            few = ", ".join(str(a) for a in missing[:8]) + ("…" if len(missing) > 8 else "")
            out.append(f"{mode.nom} : adresses sans canal ({few}). Ajoute un canal réservé (NoFeature) si c'est voulu.")
    return out


def _geo_name(c: Canal) -> str:
    if c.geometrie:
        return _clean(c.geometrie)
    return YOKE if c.attribut in ("Pan", "PanRotate") else HEAD


def _clean(name: str) -> str:
    return re.sub(r"[.\"<>&]", " ", name).strip() or HEAD


# --------------------------------------------------------------------------
# Construction du GDTF
# --------------------------------------------------------------------------

def _definition(name: str) -> dict[str, str]:
    std = attributs.gdtf_standard(name)
    if std is None:
        return {"Name": name, "Pretty": name, "Feature": "Control.Control"}
    digits = re.findall(r"\d+", name)
    pretty = std.get("pretty") or name
    for d in digits:
        pretty = re.sub(r"\((n|m)\)", d, pretty, count=1)
    out = {"Name": name, "Pretty": pretty, "Feature": std["feature"]}
    if std.get("activation_group"):
        ag = std["activation_group"]
        for d in digits:
            ag = re.sub(r"\((n|m)\)", d, ag, count=1)
        out["ActivationGroup"] = ag
    if std.get("physical_unit"):
        out["PhysicalUnit"] = std["physical_unit"]
    return out


def construire(projet: Projet) -> FixtureType:
    """Le `FixtureType` GDTF du projet. Lève `CreationError` si le projet est incomplet."""
    for mode in projet.modes:
        attribuer(mode)
    problems = verifier(projet)
    if problems:
        raise CreationError("\n".join(problems))

    root = ET.Element("GDTF", {"DataVersion": "1.2"})
    name = projet.nom.strip()
    ft = ET.SubElement(root, "FixtureType", {
        "Name": name, "ShortName": projet.court.strip() or name, "LongName": name,
        "Manufacturer": projet.fabricant.strip(), "Description": f"Créé avec {APP_NAME}",
        "FixtureTypeID": str(uuid.uuid4()).upper(), "RefFT": "", "CanHaveChildren": "Yes",
    })

    used = sorted({c.attribut for m in projet.modes for c in m.canaux})
    defs = [_definition(a) for a in used]
    ad = ET.SubElement(ft, "AttributeDefinitions")
    ags = ET.SubElement(ad, "ActivationGroups")
    for ag in sorted({d["ActivationGroup"] for d in defs if d.get("ActivationGroup")}):
        ET.SubElement(ags, "ActivationGroup", {"Name": ag})
    fgs = ET.SubElement(ad, "FeatureGroups")
    groups: dict[str, list[str]] = {}
    for d in defs:
        grp, _, feat = d["Feature"].partition(".")
        if feat not in groups.setdefault(grp, []):
            groups[grp].append(feat)
    for grp, feats in groups.items():
        fg = ET.SubElement(fgs, "FeatureGroup", {"Name": grp, "Pretty": grp})
        for feat in feats:
            ET.SubElement(fg, "Feature", {"Name": feat})
    attrs = ET.SubElement(ad, "Attributes")
    for d in defs:
        ET.SubElement(attrs, "Attribute", d)

    ET.SubElement(ft, "Wheels")
    ET.SubElement(ft, "PhysicalDescriptions")
    ET.SubElement(ft, "Models")
    geos = ET.SubElement(ft, "Geometries")
    modes_el = ET.SubElement(ft, "DMXModes")

    multi = any(c.copies > 1 and c.geometrie for m in projet.modes for c in m.canaux)
    per_mode = multi and len(projet.modes) > 1
    models: dict[str, ET.Element] = {}
    shared: Optional[dict[str, ET.Element]] = None

    for mode in projet.modes:
        suffix = f" {_clean(mode.nom)}" if per_mode else ""
        if per_mode or shared is None:
            nodes: dict[str, ET.Element] = {}
            nodes[BASE] = ET.SubElement(geos, "Geometry", {"Name": BASE + suffix})
            axes = any(c.attribut in ("Pan", "Tilt", "PanRotate", "TiltRotate")
                       for m in ([mode] if per_mode else projet.modes) for c in m.canaux)
            if axes:
                nodes[YOKE] = ET.SubElement(nodes[BASE], "Axis", {"Name": YOKE + suffix})
                nodes[HEAD] = ET.SubElement(nodes[YOKE], "Axis", {"Name": HEAD + suffix})
            else:
                nodes[HEAD] = ET.SubElement(nodes[BASE], "Geometry", {"Name": HEAD + suffix})
            if not per_mode:
                shared = nodes
        else:
            nodes = shared
        me = ET.SubElement(modes_el, "DMXMode", {"Name": mode.nom, "Geometry": nodes[BASE].get("Name"),
                                                 "Description": ""})
        chs = ET.SubElement(me, "DMXChannels")
        ET.SubElement(me, "Relations")
        ET.SubElement(me, "FTMacros")
        groups_geo = _par_geometrie(mode)
        firsts = {geo: min(a for c in cs for a in c.adresses) for geo, cs in groups_geo.items() if geo}
        for geo, cs in groups_geo.items():
            if not geo:
                continue
            model = _clean(geo)
            if model in (BASE, YOKE, HEAD):
                raise CreationError(f"{mode.nom} : « {model} » ne peut pas avoir de copies, donne un autre nom.")
            if model not in models:
                models[model] = ET.SubElement(geos, "Geometry", {"Name": model})
            first = firsts[geo]
            span = max(a for c in cs for a in c.adresses) - first + 1
            for k in range(max(c.copies for c in cs)):
                ref = ET.SubElement(nodes[HEAD], "GeometryReference",
                                    {"Name": f"{model} {k + 1}{suffix}", "Geometry": model})
                ET.SubElement(ref, "Break", {"DMXOffset": str(first + k * span), "DMXBreak": "1"})
        for c in sorted(mode.canaux, key=lambda c: c.adresse):
            if c.copies > 1 and c.geometrie:
                geo_name, shift = _clean(c.geometrie), firsts[c.geometrie] - 1
            else:
                key, shift = _geo_name(c), 0
                if key not in nodes:
                    nodes[key] = ET.SubElement(nodes[HEAD], "Geometry", {"Name": key + suffix})
                geo_name = nodes[key].get("Name")
            ce = ET.SubElement(chs, "DMXChannel", {
                "DMXBreak": "1", "Offset": ",".join(str(a - shift) for a in c.adresses),
                "Highlight": "None", "Geometry": geo_name,
            })
            lc = ET.SubElement(ce, "LogicalChannel", {"Attribute": c.attribut, "Snap": "No", "Master": "None"})
            fn_name = (c.nom or c.attribut).strip()
            cf = ET.SubElement(lc, "ChannelFunction", {
                "Name": fn_name, "Attribute": c.attribut, "OriginalAttribute": c.nom.strip(),
                "DMXFrom": "0/1", "Default": f"{max(0, min(255, c.defaut))}/1",
                "PhysicalFrom": "0", "PhysicalTo": "1",
            })
            ce.set("InitialFunction", f"{geo_name}_{c.attribut}.{c.attribut}.{fn_name}")
            for p in sorted(c.plages, key=lambda p: p.debut):
                ET.SubElement(cf, "ChannelSet", {"Name": p.nom.strip(), "DMXFrom": f"{p.debut}/1"})

    revs = ET.SubElement(ft, "Revisions")
    ET.SubElement(revs, "Revision", {"Text": f"Créé avec {APP_NAME}", "UserID": "0",
                                     "Date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
    return gdtf.parse_description(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def ecrire_gdtf(ft: FixtureType, path: Path) -> Path:
    """Enregistre le fixture en .gdtf (archive avec description.xml)."""
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("description.xml", ET.tostring(ft.xml_root, encoding="utf-8", xml_declaration=True))
    return path
