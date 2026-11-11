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

import base64
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
    groupe: str = ""  # titre de section de la notice (« Color Slot », « Ovalizer Rotation »…)
    attribut: str = ""  # fonction de la plage (Shutter1Strobe…) ; vide = à deviner
    phys_de: Optional[float] = None  # valeur physique au début / à la fin de la plage
    phys_a: Optional[float] = None


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
    description: str = ""  # texte « fonction » de la notice quand le canal n'a pas de plages
    phys_de: Optional[float] = None  # valeur physique à DMX 0 / à DMX 255 (degrés, kelvins, 0-1…)
    phys_a: Optional[float] = None

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
    images: dict[str, str] = field(default_factory=dict)  # « roue|emplacement » -> PNG en base64

    def image(self, roue: str, emplacement: str) -> Optional[bytes]:
        data = self.images.get(cle_image(roue, emplacement))
        return base64.b64decode(data) if data else None

    def definir_image(self, roue: str, emplacement: str, png: Optional[bytes]) -> None:
        """Image d'un emplacement de roue (gobo, couleur) ; None la retire."""
        if png:
            self.images[cle_image(roue, emplacement)] = base64.b64encode(png).decode("ascii")
        else:
            self.images.pop(cle_image(roue, emplacement), None)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "Projet":
        d = json.loads(text)
        modes = [Mode(m["nom"], [Canal(**{**c, "plages": [Plage(**p) for p in c.get("plages", [])]})
                                 for c in m.get("canaux", [])]) for m in d.get("modes", [])]
        return cls(d.get("fabricant", ""), d.get("nom", ""), d.get("court", ""), modes, d.get("notes", []),
                   d.get("images", {}))


def cle_image(roue: str, emplacement: str) -> str:
    return f"{roue}|{emplacement.strip().lower()}"


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
# Détail des plages : fonction (sous-attribut) et valeurs physiques
# --------------------------------------------------------------------------

_NUM = r"([-+]?\d+(?:[.,]\d+)?)"
_UNIT = r"(°|%|hz|k\b|rpm)"
_PAIR = re.compile(rf"{_NUM}\s*{_UNIT}?\s*(?:to|towards|-|→|>|/)\s*{_NUM}\s*{_UNIT}", re.I)
_ONE = re.compile(rf"{_NUM}\s*{_UNIT}", re.I)
_PLAIN_PAIR = re.compile(r"(\d\.\d+)\s*to\s*(\d\.\d+)", re.I)


def _value(text: str, unit: str) -> float:
    unit = unit.lower()
    if unit == "k" and re.fullmatch(r"[-+]?\d{1,2}[.,]\d{3}", text):
        text = re.sub(r"[.,]", "", text)  # « 2.200K » : séparateur de milliers
    v = float(text.replace(",", "."))
    if unit == "%":
        return v / 100
    if unit == "rpm":
        return v * 6  # tours/minute -> degrés/seconde
    return v


def physique(texte: str, attribut: str = "") -> Optional[tuple[float, float]]:
    """Valeurs physiques (début, fin) lues dans un texte de notice, ou None.
    « Swivelling from -25° towards 0° » -> (-25, 0) ; « 2.200K to 15.000K » -> (2200, 15000) ;
    « 0 – 100% » -> (0, 1) ; « Open » sur un shutter -> (1, 1)."""
    t = re.sub(r"degrees?|\bdeg\b", "°", texte.replace("–", "-").replace("—", "-"), flags=re.I)
    if (m := _PAIR.search(t)):
        unit = m.group(4)
        return _value(m.group(1), m.group(2) or unit), _value(m.group(3), unit)
    if (m := _ONE.search(t)):
        v = _value(m.group(1), m.group(2))
        return v, v
    if attribut.startswith("CIE_") and (m := _PLAIN_PAIR.search(t)):
        return float(m.group(1)), float(m.group(2))
    low = t.lower()
    if re.match(r"^Shutter\d+$", attribut):
        if re.search(r"\bopen\b|led on|\bon\b", low):
            return 1.0, 1.0
        if re.search(r"clos|blackout|\boff\b", low):
            return 0.0, 0.0
    if re.search(r"max\w* to min|open to clos|wide to narrow", low):
        return 1.0, 0.0
    if re.search(r"min\w* to max|clos\w* to open|narrow to wide", low):
        return 0.0, 1.0
    if attribut == "Iris" and re.fullmatch(r"\s*open\s*", low):
        return 1.0, 1.0
    if attribut == "Iris" and re.fullmatch(r"\s*closed?\s*", low):
        return 0.0, 0.0
    return None


def sous_attribut(attribut: str, texte: str) -> str:
    """Fonction précise d'une plage d'après son texte (titre de section + nom) :
    « Strobe from slow to fast » sur Shutter1 -> Shutter1Strobe. Par défaut, l'attribut du canal."""
    t = texte.lower()
    spin = bool(re.search(r"rotat|spin|rainbow|scroll|\bcw\b|\bccw\b|forward|backward", t))
    stop = bool(re.search(r"no rotation|\bstop\b", t))
    if (m := re.match(r"^Shutter(\d+)$", attribut)):
        n, rnd = m.group(1), "random" in t or "randon" in t
        if "pulse" in t:
            kind = "Open" if re.search(r"pulse (in|open)|opening", t) else "Close" if re.search(r"pulse (out|clos)|closing", t) else ""
            return f"Shutter{n}StrobeRandomPulse{kind}" if rnd else f"Shutter{n}StrobePulse{kind}"
        if rnd:
            return f"Shutter{n}StrobeRandom"
        if "strob" in t or "flash" in t:
            return f"Shutter{n}Strobe"
    elif attribut == "Iris":
        rnd = "Random" if "random" in t else ""
        if "pulse" in t and re.search(r"clos", t):
            return f"Iris{rnd}PulseClose"
        if "pulse" in t and "open" in t:
            return f"Iris{rnd}PulseOpen"
        if "strob" in t:
            return "IrisStrobeRandom" if rnd else "IrisStrobe"
    elif (m := re.match(r"^(Color|Gobo|AnimationWheel)(\d+)$", attribut)):
        fam, n = m.groups()
        if "shake" in t and fam == "Gobo":
            return f"Gobo{n}SelectShake"
        if "random" in t:
            return f"{fam}{n}WheelRandom" if fam != "AnimationWheel" else f"{fam}{n}Random"
        if "audio" in t or "sound" in t or "music" in t:
            return f"{fam}{n}WheelAudio" if fam != "AnimationWheel" else f"{fam}{n}Audio"
        if spin or stop:
            return f"{fam}{n}WheelSpin" if fam != "AnimationWheel" else f"{fam}{n}"
    elif re.match(r"^(Gobo\d+|Prism\d+|BeamShaper|AnimationWheel\d+)Pos$", attribut):
        if (spin and re.search(r"slow|fast|speed|forward|backward|\bcw\b|\bccw\b", t)) or (stop and "index" not in t):
            return attribut + "Rotate"
    elif (m := re.match(r"^Prism(\d+)$", attribut)) and spin and "index" not in t:
        return f"Prism{m.group(1)}PosRotate"
    return attribut


def detailler(mode: Mode, force: bool = False) -> None:
    """Complète les plages (fonction, physique) et la physique des canaux d'après les textes."""
    for c in mode.canaux:
        if not c.attribut:
            continue
        for p in c.plages:
            if not p.attribut or force:
                p.attribut = sous_attribut(c.attribut, f"{p.groupe} {p.nom}")
            if p.phys_de is None and p.phys_a is None:
                if (ph := physique(p.nom, p.attribut)) is not None:
                    p.phys_de, p.phys_a = ph
        if c.phys_de is None and c.phys_a is None and not c.plages:
            if (ph := physique(c.description, c.attribut)) is not None and ph[0] != ph[1]:
                c.phys_de, c.phys_a = ph


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

    def numbered(text: str) -> str:
        for d in digits:
            text = re.sub(r"\((n|m)\)", d, text, count=1)
        return text

    out = {"Name": name, "Pretty": numbered(std.get("pretty") or name), "Feature": std["feature"]}
    if std.get("activation_group"):
        out["ActivationGroup"] = numbered(std["activation_group"])
    if std.get("main"):
        out["MainAttribute"] = numbered(std["main"])
    if std.get("physical_unit"):
        out["PhysicalUnit"] = std["physical_unit"]
    return out


# Émetteurs LED : couleur (x, y) et longueur d'onde dominante TYPIQUES de chaque type de LED.
# Les notices ne donnent presque jamais ces mesures : valeurs d'usage, à affiner si le fabricant
# les publie. Clé = suffixe de l'attribut ColorAdd_*.
EMETTEURS = {
    "R": ("Red", 0.700, 0.299, 630), "G": ("Green", 0.170, 0.700, 525), "B": ("Blue", 0.152, 0.026, 450),
    "C": ("Cyan", 0.070, 0.560, 500), "M": ("Magenta", 0.385, 0.155, 0), "Y": ("Yellow", 0.480, 0.500, 575),
    "RY": ("Amber", 0.575, 0.420, 592), "GY": ("Lime", 0.410, 0.555, 566), "GC": ("Mint", 0.270, 0.480, 520),
    "BC": ("Light Blue", 0.130, 0.110, 475), "BM": ("Royal Blue", 0.157, 0.018, 445),
    "RM": ("Deep Red", 0.720, 0.280, 660), "W": ("White", 0.3127, 0.3290, 0),
    "WW": ("Warm White", 0.440, 0.403, 0), "CW": ("Cool White", 0.310, 0.320, 0), "UV": ("UV", 0.170, 0.010, 395),
}
FILTRES = {"C": ("Cyan", 0.2247, 0.3287, 78.7), "M": ("Magenta", 0.3209, 0.1542, 28.5),
           "Y": ("Yellow", 0.4193, 0.5053, 92.8)}

# Couleurs d'emplacements de roue d'après leur nom (sRGB) ; le nom le plus long l'emporte.
COULEURS = {
    "open": "ffffff", "white": "ffffff", "red": "e60000", "dark red": "8b0000", "deep red": "a00000",
    "green": "00c000", "dark green": "006400", "blue": "0030ff", "dark blue": "00008b", "deep blue": "0000a0",
    "light blue": "66b3ff", "congo": "2a0a8f", "magenta": "ff00ff", "dark magenta": "8b008b", "pink": "ff69b4",
    "cyan": "00ffff", "yellow": "ffe600", "orange": "ff8000", "amber": "ffbf00", "lavender": "b57edc",
    "purple": "800080", "violet": "7f00ff", "uv": "4b0082", "cto": "ffd9a0", "ctb": "cfe4ff",
    "lime": "bfff00", "turquoise": "40e0d0", "aqua": "00c8c8", "minus green": "ffb0ff",
}


def _xyY(hexa: str) -> str:
    rgb = [int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    X = 0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]
    Y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    Z = 0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]
    total = X + Y + Z
    if total <= 0:
        return "0.3127,0.3290,0.0"
    return f"{X / total:.4f},{Y / total:.4f},{Y * 100:.1f}"


def _luminance(x: float, y: float) -> float:
    """Luminance Y (0-100) d'un émetteur saturé : la plus forte qui garde ses composantes RVB
    dans 0-1, comme dans les fixtures de la console (un bleu pur est sombre, un lime clair)."""
    from .ma3xml import color_ma3
    rgb = [float(v) for v in color_ma3(f"{x},{y},100").split(",")[:3]]
    return 100.0 / max(1.0, max(rgb))


def couleur_emplacement(nom: str) -> str:
    low = nom.lower()
    keys = [k for k in COULEURS if re.search(rf"\b{re.escape(k)}\b", low)]
    return _xyY(COULEURS[max(keys, key=len)]) if keys else "0.3127,0.3290,100.0"


_WHEEL = re.compile(r"^(Color|Gobo|AnimationWheel|Prism)(\d+)")
_WHEEL_NAMES = {"Color": "ColorWheel", "Gobo": "GoboWheel", "AnimationWheel": "AnimationWheel", "Prism": "PrismWheel"}
_NOT_SLOT = re.compile(r"\+|&|\bto\b|→|>|rotat|spin|rainbow|shake|index|no function|reserved", re.I)


def roue_de(attribut: str) -> str:
    """Nom de la roue d'un attribut (Color1, Color1WheelSpin -> « ColorWheel 1 »), ou ''."""
    m = _WHEEL.match(attribut)
    if not m or re.search(r"Pos(Rotate)?$", attribut):
        return ""
    return f"{_WHEEL_NAMES[m.group(1)]} {m.group(2)}"


def roues(projet: Projet) -> dict[str, list[str]]:
    """Roues du fixture et leurs emplacements, tirés des plages des canaux de roue :
    chaque nom de plage entière (pas « Open + Red », pas une rotation) est un emplacement."""
    out: dict[str, list[str]] = {}
    for mode in projet.modes:
        for c in mode.canaux:
            wheel = roue_de(c.attribut)
            if not wheel or not c.plages:
                continue
            slots = out.setdefault(wheel, [])
            for p in c.plages:
                name = p.nom.strip()
                if name and (p.attribut or c.attribut) == c.attribut and not _NOT_SLOT.search(name) \
                        and name.lower() not in (s.lower() for s in slots):
                    slots.append(name)
    return {w: s for w, s in out.items() if s}


def canaux_de_roue(projet: Projet) -> dict[str, str]:
    """Roue -> noms (notice) de ses canaux, pour reconnaître la roue dont parle un titre de la notice."""
    out: dict[str, set[str]] = {}
    for mode in projet.modes:
        for c in mode.canaux:
            wheel = roue_de(c.attribut)
            if wheel:
                out.setdefault(wheel, set()).add(c.nom)
    return {w: " ".join(sorted(n)) for w, n in out.items()}


def emetteurs(projet: Projet) -> list[str]:
    """Noms des émetteurs LED créés (un par attribut ColorAdd_* utilisé)."""
    used = {c.attribut for m in projet.modes for c in m.canaux}
    return [EMETTEURS[k][0] for k in EMETTEURS if f"ColorAdd_{k}" in used]


def _num(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".") or "0"


def _alternatives(c: Canal) -> list[list[Plage]]:
    """Les plages dans l'ordre de la notice ; quand les valeurs DMX repartent en arrière, c'est une
    autre lecture du même canal (ex. indexation OU rotation, selon un autre canal)."""
    out: list[list[Plage]] = []
    for p in c.plages:
        if not out or p.debut <= out[-1][-1].debut:
            out.append([])
        out[-1].append(p)
    return out


def _maitre(mode: Mode, c: Canal, alt: list[Plage]) -> Optional[tuple[Canal, Plage]]:
    """Canal et plage qui choisissent cette lecture : une plage d'un autre canal qui porte le
    même titre (« Ovalizer Rotation (set next ch) » pour la section « Ovalizer Rotation »)."""
    titles = {t for t in ((alt[0].groupe or "").strip().lower(), alt[0].nom.strip().lower() if len(alt) == 1 else "") if t}
    for other in mode.canaux:
        if other is c:
            continue
        for p in other.plages:
            name = re.sub(r"\s*\([^)]*\)", "", p.nom).strip().lower()
            if name and any(name == t or name in t or t in name for t in titles):
                return other, p
    return None


def _fonctions(mode: Mode, c: Canal, notes: list[str]) -> list[dict]:
    """Découpe un canal en fonctions GDTF : une par suite de plages de même fonction et de même section."""
    alts = _alternatives(c)
    out: list[dict] = []
    if not alts:
        return [{"attr": c.attribut, "name": (c.nom or c.attribut).strip(), "from": 0, "plages": [],
                 "phys": (c.phys_de, c.phys_a), "master": None}]
    masters = [_maitre(mode, c, alt) if len(alts) > 1 else None for alt in alts]
    if len(alts) > 1 and not any(masters):
        notes.append(f"{mode.nom}, canal {c.adresse} « {c.nom} » : plusieurs lectures du même canal sans canal "
                     f"maître trouvé, seule la première est gardée.")
        alts, masters = alts[:1], [None]
    for alt, master in zip(alts, masters):
        if len(alts) > 1 and master is None and alt is not alts[0]:
            notes.append(f"{mode.nom}, canal {c.adresse} « {c.nom} » : section « {alt[0].groupe or alt[0].nom} » "
                         f"ignorée (pas de canal maître trouvé).")
            continue
        cur: Optional[dict] = None
        for p in alt:
            attr = p.attribut or c.attribut
            if cur is None or cur["attr"] != attr or cur["groupe"] != p.groupe:
                cur = {"attr": attr, "groupe": p.groupe, "from": p.debut, "plages": [], "master": master}
                out.append(cur)
            cur["plages"].append(p)
        first = next((f for f in out if f["master"] is master and f["plages"] and f["plages"][0] is alt[0]), None)
        if first is not None:
            first["from"] = 0  # une lecture couvre le canal depuis 0
    seen: dict[str, int] = {}
    for f in out:
        ps = f["plages"]
        name = (ps[0].nom if len(ps) == 1 else f["groupe"] or (c.nom if f["attr"] == c.attribut else f["attr"])).strip()
        name = re.sub(r"[.\"]", " ", name) or f["attr"]
        seen[name] = seen.get(name, 0) + 1
        f["name"] = name if seen[name] == 1 else f"{name} {seen[name]}"
        with_phys = [p for p in ps if p.phys_de is not None]
        f["phys"] = (with_phys[0].phys_de, with_phys[-1].phys_a) if with_phys else (
            (c.phys_de, c.phys_a) if f["attr"] == c.attribut and len(out) == 1 else (None, None))
    return out


def construire(projet: Projet) -> FixtureType:
    """Le `FixtureType` GDTF du projet. Lève `CreationError` si le projet est incomplet.
    Les remarques de construction (sections ignorées…) sont ajoutées à `projet.notes`."""
    for mode in projet.modes:
        attribuer(mode)
        detailler(mode)
    problems = verifier(projet)
    if problems:
        raise CreationError("\n".join(problems))
    notes: list[str] = []

    root = ET.Element("GDTF", {"DataVersion": "1.2"})
    name = projet.nom.strip()
    ft = ET.SubElement(root, "FixtureType", {
        "Name": name, "ShortName": projet.court.strip() or name, "LongName": name,
        "Manufacturer": projet.fabricant.strip(), "Description": f"Créé avec {APP_NAME}",
        "FixtureTypeID": str(uuid.uuid4()).upper(), "RefFT": "", "CanHaveChildren": "Yes",
    })

    used = {c.attribut for m in projet.modes for c in m.canaux}
    used |= {p.attribut for m in projet.modes for c in m.canaux for p in c.plages if p.attribut}
    defs = [_definition(a) for a in sorted(used)]
    for d in list(defs):  # un sous-attribut a besoin de son attribut principal
        main = d.get("MainAttribute")
        if main and all(x["Name"] != main for x in defs):
            defs.append(_definition(main))
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
    for d in sorted(defs, key=lambda d: bool(d.get("MainAttribute"))):  # principaux d'abord
        ET.SubElement(attrs, "Attribute", d)

    wheels = roues(projet)
    media: dict[str, bytes] = {}  # images des emplacements, rangées comme dans une archive GDTF
    we = ET.SubElement(ft, "Wheels")
    for wheel, slots in wheels.items():
        w = ET.SubElement(we, "Wheel", {"Name": wheel})
        for slot in slots:
            color = couleur_emplacement(slot) if wheel.startswith("ColorWheel") else "0.3127,0.3290,100.0"
            se = ET.SubElement(w, "Slot", {"Name": slot, "Color": color})
            png = projet.image(wheel, slot)
            if png:
                stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{wheel}_{slot}").strip("_")
                se.set("MediaFileName", stem)
                media[f"wheels/{stem}.png"] = png

    pd = ET.SubElement(ft, "PhysicalDescriptions")
    em = ET.SubElement(pd, "Emitters")
    emitter_of: dict[str, str] = {}
    for key, (ename, x, y, wave) in EMETTEURS.items():
        if f"ColorAdd_{key}" in used:
            e = ET.SubElement(em, "Emitter", {"Name": ename, "Color": f"{x:.4f},{y:.4f},{_luminance(x, y):.1f}"})
            if wave:
                e.set("DominantWaveLength", str(wave))
            emitter_of[f"ColorAdd_{key}"] = ename
    fl = ET.SubElement(pd, "Filters")
    filter_of: dict[str, str] = {}
    for key, (fname, x, y, Y) in FILTRES.items():
        if f"ColorSub_{key}" in used:
            ET.SubElement(fl, "Filter", {"Name": fname, "Color": f"{x:.4f},{y:.4f},{Y:.1f}"})
            filter_of[f"ColorSub_{key}"] = fname
    ET.SubElement(pd, "ColorSpace", {"Mode": "sRGB"})

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

        geo_of: dict[int, str] = {}
        for c in mode.canaux:
            if c.copies > 1 and c.geometrie:
                geo_of[id(c)] = _clean(c.geometrie)
            else:
                key = _geo_name(c)
                if key not in nodes:
                    nodes[key] = ET.SubElement(nodes[HEAD], "Geometry", {"Name": key + suffix})
                geo_of[id(c)] = nodes[key].get("Name")

        for c in sorted(mode.canaux, key=lambda c: c.adresse):
            geo_name = geo_of[id(c)]
            shift = firsts[c.geometrie] - 1 if c.copies > 1 and c.geometrie else 0
            ce = ET.SubElement(chs, "DMXChannel", {
                "DMXBreak": "1", "Offset": ",".join(str(a - shift) for a in c.adresses),
                "Highlight": "None", "Geometry": geo_name,
            })
            lc = ET.SubElement(ce, "LogicalChannel", {"Attribute": c.attribut, "Snap": "No", "Master": "None"})
            default = max(0, min(255, c.defaut))
            fns = _fonctions(mode, c, notes)
            plain = [f for f in fns if f["master"] is None]
            initial = next((f for f in reversed(plain) if f["from"] <= default), fns[0])
            wheel = roue_de(c.attribut)
            slots = [s.lower() for s in wheels.get(wheel, [])]
            for f in fns:
                last = max((p.fin for p in f["plages"]), default=255)
                inside = f["from"] <= default <= last or f is initial
                cf = ET.SubElement(lc, "ChannelFunction", {
                    "Name": f["name"], "Attribute": f["attr"], "OriginalAttribute": c.nom.strip(),
                    "DMXFrom": f"{f['from']}/1", "Default": f"{default if inside else f['from']}/1",
                })
                lo, hi = f["phys"]
                index = bool(slots) and f["attr"] == c.attribut
                if lo is not None and hi is not None and not index:
                    cf.set("PhysicalFrom", _num(lo))
                    cf.set("PhysicalTo", _num(hi))
                if wheel in wheels and roue_de(f["attr"]) == wheel:
                    cf.set("Wheel", wheel)
                if f["attr"] in emitter_of:
                    cf.set("Emitter", emitter_of[f["attr"]])
                if f["attr"] in filter_of:
                    cf.set("Filter", filter_of[f["attr"]])
                if f["master"] is not None:
                    master, plage = f["master"]
                    cf.set("ModeMaster", f"{geo_of[id(master)]}_{master.attribut}")
                    cf.set("ModeFrom", f"{plage.debut}/1")
                    cf.set("ModeTo", f"{plage.fin}/1")
                for p in f["plages"]:
                    cs_el = ET.SubElement(cf, "ChannelSet", {"Name": p.nom.strip(), "DMXFrom": f"{p.debut}/1"})
                    if index and p.nom.strip().lower() in slots:
                        cs_el.set("WheelSlotIndex", str(slots.index(p.nom.strip().lower()) + 1))
                    elif p.phys_de is not None and p.phys_a is not None and not index:
                        cs_el.set("PhysicalFrom", _num(p.phys_de))
                        cs_el.set("PhysicalTo", _num(p.phys_a))
            ce.set("InitialFunction", f"{geo_name}_{c.attribut}.{c.attribut}.{initial['name']}")

    revs = ET.SubElement(ft, "Revisions")
    ET.SubElement(revs, "Revision", {"Text": f"Créé avec {APP_NAME}", "UserID": "0",
                                     "Date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
    projet.notes = [n for n in projet.notes if n not in notes] + notes
    built = gdtf.parse_description(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    built.extra_files.update(media)
    return built


def ecrire_gdtf(ft: FixtureType, path: Path) -> Path:
    """Enregistre le fixture en .gdtf (archive avec description.xml)."""
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("description.xml", ET.tostring(ft.xml_root, encoding="utf-8", xml_declaration=True))
        for name, data in ft.extra_files.items():
            zf.writestr(name, data)
    return path
