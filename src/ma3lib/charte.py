"""Comparaison d'un fixture type (GDTF ou XML MA3) avec la charte DMX du constructeur.

La charte est un CSV recopié de la notice (voir chartes/*.csv) :
    mode;canal;fine;section;fonction
- canal : un numéro, ou une plage « 39-98 » ;
- fonction : texte de la notice ; plusieurs fonctions séparées par « | » se
  répètent en cycle sur la plage (Red|Green|Blue sur 39-98 = 20 pixels RGB).

Le fixture est « déplié » en adresses absolues : un canal posé sur un modèle de
référence est recopié pour chaque référence du mode, décalé de son Break.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .gdtf import DMXMode, FixtureType, Geometry

OK = "ok"
DIFF = "différence"
MANQUANT = "manquant"
EN_TROP = "en trop"
INCONNU = "à vérifier"
IGNORE = "ignoré"  # la notice dit que le canal n'est pas utilisé

UNUSED = re.compile(r"ignor|not used|unused|reserved|réservé|no function", re.I)


@dataclass
class ChartRow:
    mode: str
    coarse: int
    fine: int | None
    section: str
    function: str


@dataclass
class AbsChannel:
    addresses: list[int]
    instance: str
    attributes: list[str]
    dmx_break: int = 1  # 2 et plus : adresse DMX séparée (ex. mode « 2U » du Nando)


@dataclass
class Match:
    status: str
    address: int
    chart: ChartRow | None
    channel: AbsChannel | None
    note: str = ""
    suggestion: str = ""


# Mots de la notice -> attributs GDTF / MA3 acceptables (préfixes).
FAMILIES: list[tuple[re.Pattern, tuple[str, ...]]] = [
    (re.compile(r"control|settings|\breset\b|\blamp\b|internal program", re.I), ("Control", "NoFeature")),
    (re.compile(r"speed (pan|fan|pan/tilt|p/t)|pan/tilt.*speed|speed.*movement", re.I), ("PositionMSpeed",)),
    (re.compile(r"colou?r preset.*cross ?fade|cross ?fade.*colou?r preset|rgbw cross", re.I), ("ColorMixMode", "ColorMix")),
    (re.compile(r"colou?r preset|colou?r wheel|colou?r macro", re.I), ("Color1", "ColorMacro")),
    (re.compile(r"\blime\b", re.I), ("ColorAdd_GY", "ColorRGB_GY", "ColorAdd_L")),
    (re.compile(r"strobe ?phase|phase", re.I), ("RGB Strobe Phase", "StrobePhase", "EffectsPhase")),
    (re.compile(r"intensity effect|strobe mode|effect mode", re.I), ("StrobeMode", "Effects")),
    (re.compile(r"duration", re.I), ("StrobeDuration",)),
    (re.compile(r"flash rate|shutter|strobe rate|strobe", re.I),
     ("Shutter", "StrobeRate", "StrobeFrequency")),
    (re.compile(r"\bctc\b|\bcto\b|colou?r temp", re.I), ("CTC", "CTO", "CTB")),
    (re.compile(r"\bred\b", re.I), ("ColorAdd_R", "ColorRGB_R")),
    (re.compile(r"\bgreen\b", re.I), ("ColorAdd_G", "ColorRGB_G")),
    (re.compile(r"\bblue\b", re.I), ("ColorAdd_B", "ColorRGB_B")),
    (re.compile(r"\bamber\b", re.I), ("ColorAdd_A", "ColorRGB_A")),
    (re.compile(r"\bwhite\b(?! (overall|segment))|\bcw\b", re.I),
     ("ColorAdd_W", "ColorRGB_W", "ColorAdd_CW", "ColorRGB_CW")),
    (re.compile(r"intensity|dimmer", re.I), ("Dimmer",)),
    (re.compile(r"\bpan\b", re.I), ("Pan",)),
    (re.compile(r"\btilt\b", re.I), ("Tilt",)),
    (re.compile(r"\bzoom\b", re.I), ("Zoom",)),
    (re.compile(r"\bfocus\b", re.I), ("Focus",)),
]


def _words(text: str) -> set[str]:
    """Mots de 4 lettres ou plus, camelCase découpé (ChaseFade -> chase, fade)."""
    return set(re.findall(r"[a-z]{4,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()))


def _attr_matches(function: str, attributes: list[str], expected: tuple[str, ...]) -> bool:
    if expected and any(a.startswith(expected) or any(e.lower() in a.lower() for e in expected)
                        for a in attributes):
        return True
    # attribut maison du fabricant dont un mot long figure dans la fonction, espaces ignorés
    # (« color crossfade speed » / « Between colour preset cross fade »)
    compact = re.sub(r"[^a-z]", "", function.lower())
    if any(w in compact for a in attributes for w in _words(a) if len(w) >= 6):
        return True
    if expected:
        return False
    # fonction non répertoriée : on accepte un mot commun (« Main LED chase speed » / « Chase Speed »)
    return any(_words(function) & _words(a) for a in attributes)


def expected_attributes(function: str) -> tuple[str, ...]:
    for pattern, attrs in FAMILIES:
        if pattern.search(function):
            return attrs
    return ()


def load_chart(path: str | Path) -> list[ChartRow]:
    rows: list[ChartRow] = []
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    for rec in csv.DictReader(lines, delimiter=";"):
        canal = rec["canal"].strip()
        fine = int(rec["fine"]) if rec.get("fine", "").strip() else None
        functions = [f.strip() for f in rec["fonction"].split("|")]
        if "-" in canal:
            start, end = (int(x) for x in canal.split("-"))
            for i, addr in enumerate(range(start, end + 1)):
                rows.append(ChartRow(rec["mode"].strip(), addr, None, rec.get("section", "").strip(),
                                     functions[i % len(functions)]))
        else:
            rows.append(ChartRow(rec["mode"].strip(), int(canal), fine, rec.get("section", "").strip(),
                                 functions[0]))
    return rows


def _mode_references(ft: FixtureType, mode: DMXMode) -> dict[str, list[Geometry]]:
    root = ft.top_level(mode.geometry)
    refs: dict[str, list[Geometry]] = {}
    if root is None:
        return refs
    for g in root.walk():
        if g.is_reference:
            refs.setdefault(g.reference, []).append(g)
    return refs


def absolute_channels(ft: FixtureType, mode: DMXMode) -> list[AbsChannel]:
    """Canaux du mode en adresses absolues (canaux virtuels exclus)."""
    refs = _mode_references(ft, mode)
    out: list[AbsChannel] = []
    for ch in mode.channels:
        if ch.is_virtual:
            continue
        attrs = [lc.attribute for lc in ch.logical_channels]
        instances = refs.get(ch.geometry)
        brk = int(ch.dmx_break) if str(ch.dmx_break).isdigit() else 1
        if instances and ft.top_level(ch.geometry) is not None:
            for ref in instances:
                if ch.dmx_break == "Overwrite":  # spec GDTF : le dernier Break de la référence
                    b = ref.breaks[-1] if ref.breaks else None
                else:
                    b = next((x for x in ref.breaks if x.dmx_break == brk),
                             ref.breaks[0] if ref.breaks else None)
                shift = (b.dmx_offset - 1) if b else 0
                out.append(AbsChannel([o + shift for o in ch.offset], ref.name, attrs,
                                      b.dmx_break if b and ch.dmx_break == "Overwrite" else brk))
        else:
            out.append(AbsChannel(list(ch.offset), ch.geometry, attrs, brk))
    return sorted(out, key=lambda c: (c.dmx_break, c.addresses[0]))


def compare(ft: FixtureType, mode: DMXMode, chart: list[ChartRow]) -> list[Match]:
    """Compare un mode du fixture à la charte de la notice.

    Un mode « 2 adresses » (ex. Nando « 2U ») met une partie des canaux sur un break DMX 2 :
    la notice, elle, les numérote à la suite du break 1. On les place donc après le dernier
    canal du break 1 pour la comparaison, avec une note donnant leur adresse réelle."""
    every = absolute_channels(ft, mode)
    chans: dict[int, AbsChannel] = {}
    shift = 0
    for brk in sorted({c.dmx_break for c in every}):
        part = [c for c in every if c.dmx_break == brk]
        for c in part:
            chans[c.addresses[0] + shift] = AbsChannel([a + shift for a in c.addresses],
                                                       c.instance, c.attributes, brk)
        shift += max(a for c in part for a in c.addresses)
    fines = {a for c in chans.values() for a in c.addresses[1:]}
    out: list[Match] = []
    seen: set[int] = set()
    for row in sorted(chart, key=lambda r: r.coarse):
        ch = chans.get(row.coarse)
        seen.add(row.coarse)
        if ch is None and UNUSED.search(row.function):
            out.append(Match(IGNORE, row.coarse, row, None,
                             "canal inutilisé selon la notice : absence acceptable"))
            continue
        if ch is None:
            if row.coarse in fines:
                out.append(Match(DIFF, row.coarse, row, None,
                                 "le fixture utilise cette adresse comme Fine d'un autre canal"))
            else:
                out.append(Match(MANQUANT, row.coarse, row, None, "absent du fixture",
                                 f"ajouter un canal « {row.function} »"))
            continue
        if row.fine is not None and row.fine not in chans:
            seen.add(row.fine)
        notes, sugg = [], []
        if ch.dmx_break != 1:
            notes.append(f"break DMX {ch.dmx_break} : 2e adresse à patcher dans la console")
        gdtf_fine = ch.addresses[1] if len(ch.addresses) > 1 else None
        reserved_pair = (UNUSED.search(row.function) and gdtf_fine is not None
                         and all(a.startswith("NoFeature") for a in ch.attributes)
                         and any(r.coarse == gdtf_fine and UNUSED.search(r.function) for r in chart))
        if gdtf_fine != row.fine and not reserved_pair:
            notes.append(f"Fine notice {row.fine or 'aucun'} / fixture {gdtf_fine or 'aucun'}")
            sugg.append(f"résolution {'16 bits' if row.fine else '8 bits'}")
        expected = expected_attributes(row.function)
        status = OK
        if UNUSED.search(row.function):
            if not any(a.startswith("NoFeature") for a in ch.attributes):
                notes.append(f"canal réservé dans la notice, mais {ch.attributes[0]} dans le fixture")
                sugg.append("vérifier sur l'appareil ; NoFeature si vraiment inutilisé")
        elif not _attr_matches(row.function, ch.attributes, expected):
            if expected:
                notes.append(f"attribut {ch.attributes[0]} pour « {row.function} »")
                sugg.append(f"attribut {expected[0]}")
            else:
                status = INCONNU
                notes.append(f"fonction non reconnue, fixture : {ch.attributes[0]}")
        if sugg:
            status = DIFF
        out.append(Match(status, row.coarse, row, ch, "; ".join(notes), "; ".join(sugg)))
    fine_of = {r.fine: r.coarse for r in chart if r.fine is not None}
    for addr, ch in chans.items():
        if addr not in seen:
            if addr in fine_of:
                out.append(Match(EN_TROP, addr, None, ch,
                                 f"la notice en fait le Fine du canal {fine_of[addr]}",
                                 f"passer le canal {fine_of[addr]} en 16 bits et décaler la suite"))
            else:
                out.append(Match(EN_TROP, addr, None, ch, "absent de la notice", "vérifier ou supprimer"))
    return sorted(out, key=lambda m: m.address)
