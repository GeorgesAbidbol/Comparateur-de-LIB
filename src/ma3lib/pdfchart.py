"""Lecture de la charte DMX d'une notice PDF -> `creation.Projet`.

On cherche dans le PDF les tableaux tracés (traits) qui ressemblent à une charte :
- une ou plusieurs colonnes « numéro de canal » (une par mode ; « - » = absent du mode) ;
- une colonne de nom, et parfois fonction / valeurs DMX de-à / défaut.
Un tableau « résumé » (nom + numéros par mode) et un tableau « détail » (avec les plages)
se complètent : les lignes sont rapprochées par leurs numéros de canal.

C'est une proposition : tout reste modifiable dans l'onglet « Créer ». Les notices sans
tableau tracé (texte seul, scan) ne sont pas lues.

La logique travaille sur des `Grille` neutres (cellules + mots d'en-tête), pour être testée
sans PDF ; seul `_grilles()` dépend de pdfplumber.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import copy

from .creation import Canal, Mode, Plage, Projet, attribuer, detailler, est_fine


class PdfError(Exception):
    """PDF illisible ou sans charte DMX reconnaissable."""


@dataclass
class Grille:
    rows: list[list[str]]
    col_edges: list[tuple[float, float]] = field(default_factory=list)
    header_words: list[tuple[float, float, float, str]] = field(default_factory=list)  # x0, x1, top, texte
    row_tops: list[float] = field(default_factory=list)
    title: str = ""  # texte juste au-dessus du tableau
    page: int = 0


@dataclass
class _Entry:
    chans: list[Optional[int]]
    name: str = ""
    default: Optional[int] = None
    ranges: list[Plage] = field(default_factory=list)
    section: str = ""  # dernier titre de section vu (ligne de texte sans valeurs DMX)
    description: str = ""


@dataclass
class _Set:
    """Un jeu de modes (mêmes colonnes) et ses lignes, cumulés de tableau en tableau."""
    names: list[str]
    footprints: list[Optional[int]]
    entries: list[_Entry] = field(default_factory=list)
    index: dict[tuple, _Entry] = field(default_factory=dict)
    last: Optional[_Entry] = None


_INT = re.compile(r"^\d{1,3}$")
_DASH = re.compile(r"^[-–—/]$")
_RANGE = re.compile(r"^(\d{1,3})\s*(?:[-–—~>]+|to|à|\.\.+)\s*(\d{1,3})$", re.I)
_RANGE_HEAD = {"from", "to", "default", "défaut", "value", "values", "dmx value", "dmx", "de", "à", "valeur"}
_NAME_HEAD = {"name", "nom", "channel name", "parameter", "feature"}
_STOP = {"dmx", "mode", "modes", "function", "name", "channel", "channels", "ch", "from", "to", "default"}
MAKERS = ["PROLIGHTS", "Robe", "Ayrton", "GLP", "Chauvet", "Martin", "Clay Paky", "Claypaky", "Elation",
          "Vari-Lite", "High End", "ETC", "SGM", "JB-Lighting", "Cameo", "Astera", "Starway", "DTS",
          "ACME", "Minuit Une", "Portman", "Briteq", "ADJ", "Showtec", "Eurolite", "Stairville", "Varytec"]


def _cell(row: list[str], j: Optional[int]) -> str:
    if j is None or j >= len(row):
        return ""
    return re.sub(r"\s+", " ", row[j] or "").strip()


def _is_int(s: str) -> bool:
    return bool(_INT.match(s)) and int(s) <= 512


def _footprint_row(rows: list[list[str]]) -> Optional[int]:
    """Ligne d'en-tête qui ne contient que des nombres (le nombre de canaux de chaque mode)."""
    for i, row in enumerate(rows[:6]):
        cells = [c for c in (_cell(row, j) for j in range(len(row))) if c]
        if i and cells and all(_is_int(c) for c in cells):
            return i
    return None


def _monotonic(values: list[int]) -> bool:
    """Numéros de canal : une suite qui avance de 1 en 1 (pas des valeurs DMX 0, 2, 4…)."""
    if len(values) < 3:
        return False
    ok = sum(1 for a, b in zip(values, values[1:]) if b == a + 1)
    return ok >= 0.85 * (len(values) - 1)


def _mode_names(g: Grille, cols: list[int], header: list[list[str]]) -> list[str]:
    names = []
    for j in cols:
        words: list[tuple[float, float, str]] = []
        if g.col_edges and g.header_words:
            x0, x1 = g.col_edges[j]
            for wx0, wx1, top, text in g.header_words:
                overlap = min(x1, wx1) - max(x0, wx0)
                if overlap > 0.3 * max(1.0, min(wx1 - wx0, x1 - x0)) and text.lower() not in _STOP:
                    words.append((round(top), wx0, text))
            text = " ".join(w for _, _, w in sorted(words))
        else:
            text = " ".join(c for c in (_cell(r, j) for r in header)
                            if c and not _is_int(c) and not all(w in _STOP for w in c.lower().split()))
        names.append(text.strip())
    seen: Counter = Counter()
    for i, n in enumerate(names):
        n = n or f"Mode {i + 1}"
        seen[n] += 1
        names[i] = n if seen[n] == 1 else f"{n} {seen[n]}"
    return names


def lire_grilles(grilles: list[Grille]) -> list[Mode]:
    """Les modes décrits par une suite de tableaux (dans l'ordre du document)."""
    sets: dict[tuple, _Set] = {}
    annexes: dict[str, list[Plage]] = {}
    singles = 0
    for g in grilles:
        rows = [[(c or "") for c in r] for r in g.rows]
        if len(rows) < 3:
            continue
        ncols = max(len(r) for r in rows)
        fp = _footprint_row(rows)
        nhead = fp + 1 if fp is not None else 1
        header, body = rows[:nhead], rows[nhead:]
        stats = []
        for j in range(ncols):
            cells = [c for c in (_cell(r, j) for r in body) if c]
            nums = [c for c in cells if _is_int(c) or _DASH.match(c)]
            stats.append((len(cells), len(nums), [int(c) for c in cells if _is_int(c)]))
        numeric = [j for j, (n, k, _) in enumerate(stats) if n >= 2 and k >= 0.8 * n]
        heads = {j: {_cell(r, j).lower() for r in header} for j in range(ncols)}
        if fp is not None:
            mode_cols = [j for j in numeric if _is_int(_cell(rows[fp], j))]
        else:
            mode_cols = [j for j in numeric if not (heads[j] & _RANGE_HEAD) and _monotonic(stats[j][2])]
            mode_cols = mode_cols[:1] if mode_cols else []  # sans ligne d'empreintes : un seul mode par tableau
        if not mode_cols:
            annex = _annexe(body, numeric, stats, ncols)
            if annex and g.title:
                annexes.setdefault(_norm(g.title), []).extend(p for p in annex if p not in annexes[_norm(g.title)])
            continue
        range_cols = [j for j in numeric if j not in mode_cols and j > mode_cols[0]]
        default_col = next((j for j in range_cols if heads[j] & {"default", "défaut"}), None)
        if default_col is None and len(range_cols) >= 3:
            default_col = range_cols[2]
        from_to = [j for j in range_cols if j != default_col][:2]
        text_cols = [j for j in range(ncols) if j not in numeric and stats[j][0]]
        if not text_cols:
            continue
        name_col = next((j for j in text_cols if heads[j] & _NAME_HEAD), text_cols[0])
        func_col = next((j for j in text_cols if j != name_col), None)

        footprints = [int(_cell(rows[fp], j)) for j in mode_cols] if fp is not None else [None]
        if fp is not None:
            key: tuple = tuple(footprints)
        else:
            first = next((int(_cell(r, mode_cols[0])) for r in body if _is_int(_cell(r, mode_cols[0]))), 1)
            cur = sets.get(("seul", singles))
            if cur is None or first <= max((e.chans[0] or 0) for e in cur.entries):
                singles += 1  # la numérotation repart : nouveau mode
            key = ("seul", singles)
        s = sets.get(key)
        if s is None:
            names = _mode_names(g, mode_cols, header) if fp is not None else [g.title.strip() or f"Mode {singles}"]
            s = sets[key] = _Set(names, footprints)

        for row in body:
            chans = [int(c) if _is_int(c) else None for c in (_cell(row, j) for j in mode_cols)]
            name, func = _cell(row, name_col), _cell(row, func_col)
            if any(c is not None for c in chans):
                e = s.index.get(tuple(chans))
                if e is None:
                    e = s.index[tuple(chans)] = _Entry(chans, name)
                    s.entries.append(e)
                elif name and not e.name:
                    e.name = name
                if e is not s.last:
                    e.section = ""
                s.last = e
            e = s.last
            if e is None:
                continue
            d = _cell(row, default_col)
            if _is_int(d) and e.default is None:
                e.default = int(d)
            lo, hi = (_cell(row, from_to[0]) if from_to else ""), (_cell(row, from_to[1]) if len(from_to) > 1 else "")
            label = func
            if not _is_int(lo):  # plage écrite « 000-255 » dans une cellule de texte
                for j in text_cols:
                    m = _RANGE.match(_cell(row, j))
                    if m:
                        lo, hi = m.group(1), m.group(2)
                        label = next((_cell(row, k) for k in text_cols if k not in (j, name_col) and _cell(row, k)),
                                     "") or (name if j != name_col and not any(c is not None for c in chans) else "")
                        break
            if _is_int(lo):
                start, end = int(lo), int(hi) if _is_int(hi) else int(lo)
                prev_end = e.ranges[-1].fin if e.ranges else -1
                if (_is_int(hi) and len(lo) + len(hi) <= 3 and int(lo + hi) <= 255
                        and (end < start or start <= prev_end < int(lo + hi))):
                    start = end = int(lo + hi)  # « 26 » centré sur les colonnes de/à, lu « 2 » et « 6 »
                p = Plage(start, end, label, e.section)
                if p.fin <= 255 and p not in e.ranges:
                    e.ranges.append(p)
                if start == 0 and end >= 255 and label and not e.description:
                    e.description = label
            elif func and not any(c is not None for c in chans) and not re.match(r"\(?(check|see|voir)\b", func, re.I):
                e.section = func  # titre de section : « Color Slot », « Ovalizer Rotation »…
            elif func and any(c is not None for c in chans):
                if re.match(r"\(?(check|see|voir)\b", func, re.I):
                    e.section = ""
                else:
                    e.section = func
                    e.description = e.description or func

    modes: list[Mode] = []
    for s in sets.values():
        for i, mode_name in enumerate(s.names):
            mode = Mode(mode_name)
            rows_i = sorted((e for e in s.entries if e.chans[i] is not None), key=lambda e: e.chans[i])
            prev: Optional[Canal] = None
            prev_e: Optional[_Entry] = None
            for e in rows_i:
                addr = e.chans[i]
                base = re.sub(r"\bfine\b|\blsb\b", "", e.name, flags=re.I).strip().lower()
                if (prev is not None and prev.fine is None and addr == prev.adresse + 1
                        and (not e.name or (est_fine(e.name) and (not base or prev.nom.lower().startswith(base))))):
                    prev.fine = addr
                    if not e.name:
                        prev.plages += [copy.deepcopy(p) for p in e.ranges if p not in prev.plages]
                        _tidy(prev)
                    continue
                prev = Canal(addr, None, re.sub(r"\s*\((check|see|voir)[^)]*\)", "", e.name, flags=re.I).strip(),
                             defaut=e.default or 0, plages=copy.deepcopy(e.ranges), description=e.description)
                _tidy(prev)
                prev_e = e
                mode.canaux.append(prev)
            if len(mode.canaux) >= 3:
                attribuer(mode)
                for c in mode.canaux:  # liste complète donnée dans un tableau à part (« see full list »)
                    key = _norm(c.nom)
                    full = next((ps for title, ps in annexes.items()
                                 if key and title.split()[:1] == key.split()[:1]
                                 and (title.startswith(key) or key.startswith(title))), None)
                    if full and len(full) > len(c.plages):
                        c.plages = copy.deepcopy(full)
                detailler(mode)
                modes.append(mode)
    return modes


def _norm(text: str) -> str:
    text = re.sub(r"\([^)]*\)|\bchannel\b|\b\d+ ?bits?\b", " ", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _annexe(body: list[list[str]], numeric: list[int], stats: list, ncols: int) -> list[Plage]:
    """Tableau de valeurs sans numéro de canal (« Control Channel » : fonction, de, à) :
    la liste complète des plages d'un canal, donnée à part dans la notice."""
    pair = next(((a, b) for a, b in zip(numeric, numeric[1:]) if b == a + 1), None)
    if pair is None:
        return []
    text_cols = [j for j in range(pair[0]) if j not in numeric and stats[j][0]]
    if not text_cols:
        return []
    out: list[Plage] = []
    carried = ""
    for row in body:
        lo, hi = _cell(row, pair[0]), _cell(row, pair[1])
        cells = [_cell(row, j) for j in text_cols]
        if len(text_cols) > 1:
            carried = cells[0] or carried
            label = " ".join(t for t in [carried] + cells[1:] if t)
        else:
            label = cells[0]
        if _is_int(lo) and int(lo) <= 255 and re.search(r"[A-Za-z]{2}", label):  # un nom, pas des nombres
            end = int(hi) if _is_int(hi) else int(lo)
            if out and int(lo) <= out[-1].debut:
                return []  # les valeurs repartent en arrière : ce n'est pas une liste de plages
            if end <= 255:
                out.append(Plage(int(lo), end, label))
    return out if len(out) >= 4 else []


def _tidy(c: Canal) -> None:
    """L'ordre de la notice est gardé : des valeurs qui repartent de 0 sont une autre section."""
    if len(c.plages) == 1 and c.plages[0].debut == 0 and c.plages[0].fin >= 255:
        c.plages = []  # une seule plage pleine échelle : rien à nommer


# --------------------------------------------------------------------------
# Chartes « empilées » (Martin…) : une case par canal, les valeurs DMX et leurs
# libellés empilés ligne à ligne dans la case, alignés par leur hauteur.
# --------------------------------------------------------------------------

@dataclass
class Ligne:
    valeur: str  # « 0 - 19 », « 15 », « 0 - 65535 » ou vide
    texte: str
    style: str = ""  # « gras » (nom du canal), « ital » (titre de section) ou vide
    top: float = 0.0
    bottom: float = 0.0


@dataclass
class Bloc:
    """Un canal : ses numéros dans chaque mode (plusieurs = 16 bits ; aucun = absent), ses lignes."""
    chans: list[list[int]]
    lignes: list[Ligne] = field(default_factory=list)
    defaut: str = ""


@dataclass
class Pile:
    modes: list[str]
    blocs: list[Bloc] = field(default_factory=list)
    cols: tuple = ()  # colonnes reconnues (pour un tableau de suite) : nombre, valeurs, modes, fonction, défaut


_VAL = re.compile(r"^(\d{1,5})(?:\s*[-–—]\s*(\d{1,5}))?$")
_OCTETS = re.compile(r",?\s*(?:16[- ]bit\s*)?\((?:[^)]*\b(?:MSB|LSB)\b[^)]*)\)", re.I)


def _nom_et_lignes(b: Bloc) -> tuple[str, list[Ligne]]:
    """Les premières lignes sans valeur sont le nom du canal (en gras quand la notice le marque)."""
    head: list[Ligne] = []
    for ln in b.lignes:
        if ln.valeur or (head and (ln.style != head[0].style or ln.top - head[-1].bottom > 0.6 * (ln.bottom - ln.top))):
            break
        head.append(ln)
    return " ".join(ln.texte for ln in head).strip(), b.lignes[len(head):]


def lire_piles(piles: list[Pile]) -> list[Mode]:
    """Les modes décrits par des tableaux « empilés » (dans l'ordre du document)."""
    sets: dict[tuple, Pile] = {}
    for p in piles:
        s = sets.setdefault(tuple(p.modes), Pile(list(p.modes)))
        s.blocs.extend(p.blocs)
    modes: list[Mode] = []
    for s in sets.values():
        entries = []
        for b in s.blocs:
            name, lignes = _nom_et_lignes(b)
            numbers = [int(x) for ln in lignes if ln.valeur and _VAL.match(ln.valeur)
                       for x in _VAL.match(ln.valeur).groups() if x]
            wide = any(n > 255 for n in numbers)  # valeurs 16 bits : on garde l'octet de poids fort
            plages: list[Plage] = []
            section, prev = "", None
            for ln in lignes:
                m = _VAL.match(ln.valeur) if ln.valeur else None
                near = prev is not None and ln.top - prev.bottom < 0.5 * (ln.bottom - ln.top)
                if m:
                    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
                    if wide:
                        lo, hi = lo >> 8, hi >> 8
                        if plages and plages[-1].groupe == section and lo <= plages[-1].fin < hi:
                            lo = plages[-1].fin + 1
                    if hi <= 255:
                        plages.append(Plage(lo, hi, ln.texte, section))
                elif ln.texte:
                    if near and prev.valeur and plages and ln.style == prev.style:
                        plages[-1].nom = f"{plages[-1].nom} {ln.texte}".strip()  # libellé sur deux lignes
                    elif near and not prev.valeur:
                        section = f"{section} {ln.texte}".strip()
                    else:
                        section = ln.texte
                prev = ln
            for q in plages:  # « Indexed gobo: set indexed angle on channels 9/10… » -> « Indexed gobo »
                q.groupe = re.split(r":\s", q.groupe + " ")[0].strip().rstrip(":")
            d = b.defaut.strip()
            default = (int(d) >> 8 if int(d) > 255 else int(d)) if d.isdigit() else 0
            entries.append((b.chans, name, plages, default))
        for i, mode_name in enumerate(s.modes):
            mode = Mode(mode_name or f"Mode {i + 1}")
            prev_c: Optional[Canal] = None
            for chans, name, plages, default in sorted((e for e in entries if i < len(e[0]) and e[0][i]),
                                                       key=lambda e: e[0][i][0]):
                addr = chans[i][0]
                base = re.sub(r"\bfine\b|\blsb\b|[(),]", "", name, flags=re.I).strip().lower()
                if (prev_c is not None and prev_c.fine is None and addr == prev_c.adresse + 1 and len(chans[i]) == 1
                        and est_fine(name) and (not base or _OCTETS.sub("", prev_c.nom).strip().lower().startswith(base)
                                                or prev_c.nom.lower().startswith(base))):
                    prev_c.fine = addr
                    continue
                full = len(plages) == 1 and plages[0].debut == 0 and plages[0].fin >= 255
                prev_c = Canal(addr, chans[i][1] if len(chans[i]) > 1 else None, _OCTETS.sub("", name).strip(),
                               defaut=default, plages=copy.deepcopy(plages),
                               description=plages[0].nom if full else "")
                _tidy(prev_c)
                mode.canaux.append(prev_c)
            if len(mode.canaux) >= 3:
                attribuer(mode)
                detailler(mode)
                modes.append(mode)
    return modes


def _pile(page, table, rows: list, prev: Optional[Pile] = None) -> Optional[Pile]:
    """Le tableau lu comme une charte empilée, ou None s'il n'en est pas une.
    `prev` : la charte empilée déjà lue ; un tableau de mêmes colonnes en est la suite
    (dernière page, canaux réservés sans valeurs)."""
    starts = sorted({round(c[0], 1) for c in table.cells})
    edges = [(a, b) for a, b in zip(starts, starts[1:] + [table.bbox[2]])]
    ncols = len(edges)
    cells = [[(r[j] if j < len(r) and r[j] else "") for j in range(ncols)] for r in rows]

    def col_lines(j: int) -> list[str]:
        return [ln.strip() for r in cells for ln in r[j].splitlines() if ln.strip()]

    counts = [sum(1 for ln in col_lines(j) if _VAL.match(ln) and "-" in ln.replace("–", "-")) for j in range(ncols)]
    stacked = any(sum(1 for ln in r[j].splitlines() if _VAL.match(ln.strip())) >= 2 for r in cells for j in range(ncols))
    if stacked and max(counts, default=0) >= 3:
        x0, top, x1, _ = table.bbox
        above = page.crop((max(0, x0 - 2), max(0, top - 60), min(page.width, x1 + 2), max(1, top))).extract_words()
        keep: set[int] = set()
        last = top
        for y in sorted({round(w["top"]) for w in above}, reverse=True):  # les lignes d'en-tête collées au tableau
            if last - y > 16:
                break
            keep.add(y)
            last = y
        heads = [" ".join(w["text"] for w in sorted((w for w in above if round(w["top"]) in keep
                                                      and a - 3 <= (w["x0"] + w["x1"]) / 2 <= b + 3),
                                                     key=lambda w: (round(w["top"]), w["x0"]))) for a, b in edges]
        ranged = [j for j in range(ncols) if counts[j] >= 2 and not re.search(r"percent|%|pour ?cent", heads[j], re.I)]
        if not ranged:
            return None
        value_col = next((j for j in ranged if re.search(r"dmx|val", heads[j], re.I)), ranged[0])

        def number_col(j: int) -> bool:
            vals = [c[j].strip() for c in cells if c[j].strip()]
            return any(_is_int(v) for v in vals) and all(_is_int(v) or _DASH.match(v) for v in vals)

        mode_cols = [j for j in range(value_col) if number_col(j)]
        text_cols = [j for j in range(value_col + 1, ncols) if j not in ranged]
        if not mode_cols or not text_cols:
            return None
        func_col = max(text_cols, key=lambda j: sum(len(re.findall(r"[A-Za-z]", c[j])) for c in cells))
        default_col = next((j for j in range(ncols) if re.search(r"default|défaut", heads[j], re.I)), None)
        pile = Pile([re.sub(r"\s+", " ", heads[j]).strip() for j in mode_cols],
                    cols=(ncols, value_col, tuple(mode_cols), func_col, default_col))
    elif prev is not None and prev.cols and prev.cols[0] == ncols:
        _, value_col, mode_cols, func_col, default_col = prev.cols
        pile = Pile(list(prev.modes), cols=prev.cols)
    else:
        return None

    boxes: list[list[float]] = []
    for r, row in zip(cells, table.rows):
        nums = [[int(r[j])] if _is_int(r[j].strip()) else [] for j in mode_cols]
        if r[func_col].strip() or r[value_col].strip():
            pile.blocs.append(Bloc(nums, defaut=r[default_col].strip() if default_col is not None else ""))
            boxes.append([row.bbox[1], row.bbox[3]])
        elif pile.blocs and any(nums):  # case fusionnée : les octets suivants du même canal
            for have, more in zip(pile.blocs[-1].chans, nums):
                have.extend(more)
            boxes[-1][1] = row.bbox[3]
    words = page.extract_words(extra_attrs=["fontname"])

    def lines_in(col: int, y0: float, y1: float) -> list[Ligne]:
        a, b = edges[col]
        out: list[list[dict]] = []
        for w in sorted((w for w in words if y0 - 0.5 <= (w["top"] + w["bottom"]) / 2 <= y1 + 0.5
                         and a <= (w["x0"] + w["x1"]) / 2 <= b), key=lambda w: (w["top"], w["x0"])):
            if out and abs(w["top"] - out[-1][0]["top"]) <= 3:
                out[-1].append(w)
            else:
                out.append([w])
        res = []
        for g in out:
            g.sort(key=lambda w: w["x0"])
            font = g[0]["fontname"].lower()
            style = "gras" if "bold" in font else "ital" if re.search(r"ital|obli", font) else ""
            res.append(Ligne("", " ".join(w["text"] for w in g), style,
                             min(w["top"] for w in g), max(w["bottom"] for w in g)))
        return res

    for b, (y0, y1) in zip(pile.blocs, boxes):
        values, texts = lines_in(value_col, y0, y1), lines_in(func_col, y0, y1)
        aligned = all(any(abs(v.top - t.top) <= 3 for t in texts) for v in values)
        plain = [t for t in texts if not t.style]
        for k, v in enumerate(values):
            if aligned:
                target = next(t for t in texts if abs(v.top - t.top) <= 3)
            elif len(plain) == len(values):  # case des valeurs décalée en hauteur : même nombre, même ordre
                target = plain[k]
            else:
                target = next((t for t in plain if not t.valeur and t.top >= v.top - 3), None)
            if target is None or target.valeur:
                texts.append(Ligne(v.texte, "", "", v.top, v.bottom))
            else:
                target.valeur = v.texte
        b.lignes = sorted(texts, key=lambda t: t.top)
    return pile


# --------------------------------------------------------------------------
# pdfplumber
# --------------------------------------------------------------------------

def _grilles(path: Path, piles: Optional[list[Pile]] = None) -> tuple[list[Grille], str]:
    """Tableaux du PDF. Les chartes empilées vont dans `piles` (si donné) au lieu des grilles."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise PdfError("Il manque le module pdfplumber (relance « Banane Pot.bat » pour l'installer).") from exc
    out: list[Grille] = []
    texts: list[str] = []
    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:
        raise PdfError(f"{Path(path).name} : PDF illisible ({exc})") from exc
    likely, whole = _pages_probables(path)
    texts.append(whole)
    pile_page = 0
    with pdf:
        for n, page in enumerate(pdf.pages, 1):
            if n <= 2 or n == len(pdf.pages):
                texts.append(page.extract_text() or "")
            if likely is not None and n not in likely and pile_page != n - 1:
                continue  # (la page qui suit une charte empilée peut en porter la fin : canaux réservés)
            if not (n <= 2 or n == len(pdf.pages)):
                texts.append(page.extract_text() or "")
            if len(page.lines) + len(page.rects) < 6:
                continue
            try:
                found = page.find_tables()
            except Exception:
                continue
            for t in found:
                x0, top, x1, bottom = t.bbox
                box = (max(0, x0 - 2), max(0, top - 2), min(page.width, x1 + 2), min(page.height, bottom + 2))
                crop = page.crop(box)
                xs = {round(l["x0"], 1) for l in crop.lines if abs(l["x0"] - l["x1"]) < 1}
                for r in crop.rects:
                    xs |= {round(r["x0"], 1), round(r["x1"], 1)}
                xs |= {round(x0, 1), round(x1, 1)}
                merged: list[float] = []
                for x in sorted(xs):  # traits doublés à moins de 2 points : un seul bord
                    if not merged or x - merged[-1] > 2:
                        merged.append(x)
                try:
                    tables = crop.find_tables({"vertical_strategy": "explicit", "explicit_vertical_lines": merged,
                                               "horizontal_strategy": "lines"})
                except Exception:
                    tables = []
                best = max(tables, key=lambda tb: len(tb.rows), default=t)
                rows = best.extract()
                if not rows:
                    continue
                if piles is not None:
                    try:
                        pile = _pile(page, best, rows, piles[-1] if piles else None)
                    except Exception:
                        pile = None
                    if pile is not None:
                        piles.append(pile)
                        pile_page = n
                        continue
                _recoller(rows, best, crop.extract_words())
                starts = sorted({round(c[0], 1) for c in best.cells})
                edges = [(a, b) for a, b in zip(starts, starts[1:] + [best.bbox[2]])]
                tops = [r.bbox[1] for r in best.rows]
                fp = _footprint_row([[c or "" for c in r] for r in rows])
                limit = tops[fp] if fp is not None and fp < len(tops) else (tops[1] if len(tops) > 1 else top)
                words = [(w["x0"], w["x1"], w["top"], w["text"]) for w in crop.extract_words()
                         if w["top"] < limit - 1]
                above = page.crop((0, max(0, top - 40), page.width, max(1, top))).extract_text() or ""
                lines = [ln.strip() for ln in above.splitlines() if ln.strip()]
                title = next((ln for ln in reversed(lines) if re.search(r"mode|\bch\b|channel|canaux", ln, re.I)),
                             lines[-1] if lines else "")
                out.append(Grille(rows, edges, words, tops, title, n))
    return out, "\n".join(texts)


def _recoller(rows: list, table, words: list) -> None:
    """Une cellule fusionnée sur deux colonnes est coupée en deux par le bord de colonne
    (« NO FUNCT » | « ION / SAFE », « 2 » | « 6 ») : on recolle quand un mot chevauche le bord."""
    starts = sorted({round(c[0], 1) for c in table.cells})
    for i, row in enumerate(table.rows):
        if i >= len(rows):
            break
        top, bottom = row.bbox[1], row.bbox[3]
        inside = [w for w in words if top - 1 <= (w["top"] + w["bottom"]) / 2 <= bottom + 1]
        for j in range(len(starts) - 1, 0, -1):  # de droite à gauche : les fusions s'enchaînent
            edge = starts[j]
            if j < len(rows[i]) and rows[i][j - 1] and rows[i][j] and any(
                    w["x0"] < edge - 1.5 and w["x1"] > edge + 1.5 for w in inside):
                rows[i][j - 1] = rows[i][j - 1] + rows[i][j]
                rows[i][j] = ""


def _pages_probables(path: Path) -> tuple[Optional[set[int]], str]:
    """Pages qui peuvent porter une charte (beaucoup de petits nombres + un mot-clé), et le texte
    de tout le document. Tri rapide avec pdfium : pdfplumber met plusieurs secondes sur une page
    de dessins."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return None, ""
    out: set[int] = set()
    texts: list[str] = []
    try:
        for i in range(len(doc)):
            text = doc[i].get_textpage().get_text_range()
            texts.append(text)
            if (len(re.findall(r"(?<![\w.,])\d{1,3}(?![\w.,])", text)) >= 40
                    and re.search(r"dmx|channel|canal|mode|value|valeur", text, re.I)):
                out.add(i + 1)
    finally:
        doc.close()
    return out, "\n".join(texts)


_DEG = r"(\d+(?:[.,]\d+)?)\s*°"
_SEP = r"\s*(?:-|–|~|to|/)\s*"


def appliquer_faits(projet: Projet, text: str) -> None:
    """Données générales de la notice appliquées aux canaux : course du pan et du tilt
    (« Pan movement range: 540° »), plage du zoom (« 10°-60° zoom »)."""
    text = re.sub(r"(?:[ \t]*\.){3,}[ \t]*", " : ", text)  # « Pan. . . . . . 540° » : points de conduite

    def find(pattern: str) -> Optional[tuple[float, ...]]:
        m = re.search(pattern, text, re.I)
        return tuple(float(g.replace(",", ".")) for g in m.groups() if g) if m else None

    # « Pan movement range: 540° », « Pan 0-540° », « Tilt: 270° »
    course = r"(?![^\n]{0,12}lock)[^\n\d°]{0,40}?(?:0\s*°?" + _SEP + r")?(\d{3})\s*°"
    spans = {"Pan": find(r"\bpan\b" + course), "Tilt": find(r"\btilt\b" + course)}
    # « blade angle adjustment of min. ±25° », « module rotation of min. ±60° », « Frame rotation ±45° »
    pm = r"[^\n\d±]{0,40}?(?:±|\+/-|\+-)\s*(\d+(?:[.,]\d+)?)\s*°"
    blade = find(r"blades?\b[^\n]{0,25}?(?:angle|swivel|tilt)" + pm)
    frame = find(r"(?:module|frame|framing system|shutter system)\s+rotation" + pm)
    zoom = find(_DEG + _SEP + _DEG + r"[^\n]{0,12}zoom") or find(r"zoom[^\n\d]{0,30}" + _DEG + _SEP + _DEG)
    # « strobe and pulse effects with variable speed from approx. 2 Hz to 10 Hz »
    hz = r"(\d+(?:[.,]\d+)?)\s*Hz"
    strobe = find(r"strob[^\n]{0,90}?" + hz + _SEP + hz) or find(hz + _SEP + hz + r"[^\n]{0,20}strob")
    if strobe and len(strobe) == 2:
        lo, hi = sorted(strobe)
        for mode in projet.modes:
            for c in mode.canaux:
                for p in c.plages:
                    if re.fullmatch(r"Shutter\d+Strobe(Random)?", p.attribut or "") and p.phys_de is None:
                        down = re.search(r"fast\W{1,4}(to\W)?slow", p.nom, re.I)
                        p.phys_de, p.phys_a = (hi, lo) if down else (lo, hi)
    for mode in projet.modes:
        for c in mode.canaux:
            if len(c.plages) > 1 or any(p.phys_de is not None for p in c.plages):
                continue  # la charte donne déjà la physique plage par plage
            if c.phys_de is not None and (c.attribut != "Zoom" or {c.phys_de, c.phys_a} != {0.0, 1.0}):
                continue
            angle = (blade if re.fullmatch(r"Blade\d+Rot", c.attribut) else frame if c.attribut == "ShaperRot"
                     else None)
            if angle:
                c.phys_de, c.phys_a = -angle[0], angle[0]
            elif spans.get(c.attribut):
                half = spans[c.attribut][0] / 2
                c.phys_de, c.phys_a = -half, half
            elif c.attribut == "Zoom" and zoom and len(zoom) == 2:
                lo, hi = sorted(zoom)
                reverse = re.search(r"max\w* to min|wide to narrow|flood\W{1,4}(to\W)?spot", c.description, re.I)
                c.phys_de, c.phys_a = (hi, lo) if reverse else (lo, hi)


_LISTE = re.compile(r"^\W*(\d{1,2})\.\s*(.+?)\s*(?:\.{2,}|…|\s-\s*P/N).*$")
_SLOT = re.compile(r"^\W*Slot\s+(\d{1,2})\s*-\s*(.+?)\s*(?:-\s*P/N.*|Slot\s+\d.*)?$", re.I)


def nommer_emplacements(projet: Projet, text: str) -> int:
    """Noms des filtres et des gobos donnés par la notice, posés sur les plages « Slot 3 », « Gobo 2 » :
    « Slot 1 - Blue 101 - P/N … » (roue de couleurs) ; « Breakup wheel (wheel 1) » suivi de
    « 1. Dots in space ..... P/N … » (roue de gobos). Les images déjà posées suivent le nouveau nom.
    Renvoie le nombre d'emplacements renommés."""
    from .creation import canaux_de_roue, cle_image, roue_de
    from .pdfimages import choisir_roue
    lines = [ln.strip() for ln in text.splitlines()]
    todo: list[tuple[str, str, dict[str, str]]] = []  # roue, mot (« Slot », « Gobo »), numéro -> nom
    slots: dict[str, str] = {}
    for ln in lines:
        if (m := _SLOT.match(ln)) and m.group(1) not in slots and not re.fullmatch(r"open", m.group(2), re.I):
            slots[m.group(1)] = m.group(2).strip()
    noms = canaux_de_roue(projet)

    def uses(wheel: str, word: str) -> bool:
        return any(re.search(rf"\b{word} ?\d", p.nom, re.I) for m in projet.modes for c in m.canaux
                   if roue_de(c.attribut) == wheel for p in c.plages)

    if len(slots) >= 3:
        users = [w for w in noms if uses(w, "Slot")]
        if len(users) == 1:
            todo.append((users[0], "Slot", slots))
    for i, ln in enumerate(lines):
        if not re.search(r"wheel|roue", ln, re.I) or len(ln) > 60 or _LISTE.match(ln):
            continue
        found: dict[str, str] = {}
        for nxt in lines[i + 1:i + 16]:
            m = _LISTE.match(nxt)
            if not m:
                break
            found[m.group(1)] = re.sub(r"\s*\([^)]*\)", "", m.group(2)).strip(" .")
        wheel = choisir_roue(ln, noms) if len(found) >= 2 else ""
        if wheel and uses(wheel, "Gobo") and not any(t[0] == wheel for t in todo):
            todo.append((wheel, "Gobo", found))
    count = 0
    for wheel, word, names in todo:
        done: set[str] = set()
        for mode in projet.modes:
            for c in mode.canaux:
                if roue_de(c.attribut) != wheel:
                    continue
                for p in c.plages:
                    old = p.nom
                    p.nom = re.sub(rf"\b{word} ?(\d+)\b", lambda m: names.get(m.group(1), m.group(0)), p.nom, flags=re.I)
                    if p.nom != old and old.lower() not in done and re.fullmatch(rf"{word} ?\d+", old.strip(), re.I):
                        done.add(old.lower())
                        png = projet.image(wheel, old)
                        if png:
                            projet.definir_image(wheel, old, None)
                            projet.definir_image(wheel, p.nom, png)
        count += len(done)
    return count


def _fabricant(text: str) -> str:
    counts = {m: len(re.findall(rf"\b{re.escape(m)}\b", text, re.I)) for m in MAKERS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ""


_GENERIC = re.compile(r"user|manual|guide|notice|version|english|français|safety|installation|^rev\b|www\.|©", re.I)


def _nom(path: Path, text: str = "") -> str:
    """Nom du projecteur : la première ligne de la notice qui n'est pas « User manual »…, sinon le nom du fichier."""
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()][:5]:
        clean = re.sub(r"[™®©]", "", line).strip()
        if 3 <= len(clean) <= 40 and re.search(r"[A-Za-z]{3}", clean) and not _GENERIC.search(clean):
            return clean
    stem = re.sub(r"(?i)[_\- ]*(user[_ ]?manual|manual|dmx[_ ]?chart|dmx|notice|en|fr|v\d+|rev\w*)(?=[_\- ]|$)", "",
                  Path(path).stem)
    return re.sub(r"[_\-]+", " ", stem).strip() or Path(path).stem


def lire_pdf(path: str | Path) -> Projet:
    """Projet proposé à partir de la notice. Lève `PdfError` si aucune charte n'est trouvée."""
    path = Path(path)
    piles: list[Pile] = []
    grilles, text = _grilles(path, piles)
    modes = lire_piles(piles) + lire_grilles(grilles)
    if not modes:
        raise PdfError(f"{path.name} : aucune charte DMX en tableau trouvée. "
                       "Tu peux saisir les canaux à la main, ou m'envoyer le PDF pour que j'adapte la lecture.")
    projet = Projet(_fabricant(text), _nom(path, text), "", modes)
    appliquer_faits(projet, text)
    try:
        from .pdfimages import images_des_roues
        images_des_roues(path, projet)
    except Exception as exc:  # les images sont un plus : la charte lue reste utilisable
        projet.notes.append(f"images des roues non lues ({exc})")
    nommer_emplacements(projet, text)
    for m in modes:
        addrs = sorted(a for c in m.canaux for a in c.adresses)
        missing = [a for a in range(1, addrs[-1] + 1) if a not in addrs]
        if missing:
            projet.notes.append(f"{m.nom} : adresses non lues dans le PDF : {', '.join(map(str, missing[:10]))}")
    return projet
