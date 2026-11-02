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
    (re.compile(r"control|settings|reset|lamp", re.I), ("Control", "NoFeature")),
    (re.compile(r"strobe ?phase|phase", re.I), ("RGB Strobe Phase", "StrobePhase", "EffectsPhase")),
    (re.compile(r"intensity effect|strobe mode|effect mode", re.I), ("StrobeMode", "Effects")),
    (re.compile(r"duration", re.I), ("StrobeDuration",)),
    (re.compile(r"flash rate|shutter|strobe rate|strobe", re.I),
     ("Shutter", "StrobeRate", "StrobeFrequency")),
    (re.compile(r"\bctc\b|color temp", re.I), ("CTC", "CTO", "CTB")),
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
        if instances and ft.top_level(ch.geometry) is not None:
            for ref in instances:
                shift = (ref.breaks[0].dmx_offset - 1) if ref.breaks else 0
                out.append(AbsChannel([o + shift for o in ch.offset], ref.name, attrs))
        else:
            out.append(AbsChannel(list(ch.offset), ch.geometry, attrs))
    return sorted(out, key=lambda c: c.addresses[0])


def compare(ft: FixtureType, mode: DMXMode, chart: list[ChartRow]) -> list[Match]:
    chans = {c.addresses[0]: c for c in absolute_channels(ft, mode)}
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
        gdtf_fine = ch.addresses[1] if len(ch.addresses) > 1 else None
        if gdtf_fine != row.fine:
            notes.append(f"Fine notice {row.fine or 'aucun'} / fixture {gdtf_fine or 'aucun'}")
            sugg.append(f"résolution {'16 bits' if row.fine else '8 bits'}")
        expected = expected_attributes(row.function)
        status = OK
        if not expected:
            status = INCONNU
            notes.append("fonction de la notice non reconnue")
        elif not any(a.startswith(expected) for a in ch.attributes):
            notes.append(f"attribut {ch.attributes[0]} pour « {row.function} »")
            sugg.append(f"attribut {expected[0]}")
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
