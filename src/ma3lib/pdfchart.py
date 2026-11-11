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

from .creation import Canal, Mode, Plage, Projet, attribuer, est_fine


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
                p = Plage(int(lo), int(hi) if _is_int(hi) else int(lo), label)
                if p.fin <= 255 and p not in e.ranges:
                    e.ranges.append(p)

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
                        prev.plages += [p for p in e.ranges if p not in prev.plages]
                        _tidy(prev)
                    continue
                prev = Canal(addr, None, re.sub(r"\s*\((check|see|voir)[^)]*\)", "", e.name, flags=re.I).strip(),
                             defaut=e.default or 0, plages=list(e.ranges))
                _tidy(prev)
                prev_e = e
                mode.canaux.append(prev)
            if len(mode.canaux) >= 3:
                attribuer(mode)
                modes.append(mode)
    return modes


def _tidy(c: Canal) -> None:
    c.plages.sort(key=lambda p: (p.debut, p.fin))
    if len(c.plages) == 1 and c.plages[0].debut == 0 and c.plages[0].fin >= 255:
        c.plages = []  # une seule plage pleine échelle : rien à nommer


# --------------------------------------------------------------------------
# pdfplumber
# --------------------------------------------------------------------------

def _grilles(path: Path) -> tuple[list[Grille], str]:
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
    likely = _pages_probables(path)
    with pdf:
        for n, page in enumerate(pdf.pages, 1):
            if n <= 2 or n == len(pdf.pages):
                texts.append(page.extract_text() or "")
            if likely is not None and n not in likely:
                continue
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
                starts = sorted({round(c[0], 1) for c in best.cells})
                edges = [(a, b) for a, b in zip(starts, starts[1:] + [best.bbox[2]])]
                tops = [r.bbox[1] for r in best.rows]
                fp = _footprint_row([[c or "" for c in r] for r in rows])
                limit = tops[fp] if fp is not None and fp < len(tops) else (tops[1] if len(tops) > 1 else top)
                words = [(w["x0"], w["x1"], w["top"], w["text"]) for w in crop.extract_words()
                         if w["top"] < limit - 1]
                above = page.crop((0, max(0, top - 40), page.width, max(1, top))).extract_text() or ""
                title = next((ln.strip() for ln in reversed(above.splitlines())
                              if re.search(r"mode|\bch\b|channel|canaux", ln, re.I)), "")
                out.append(Grille(rows, edges, words, tops, title, n))
    return out, "\n".join(texts)


def _pages_probables(path: Path) -> Optional[set[int]]:
    """Pages qui peuvent porter une charte (beaucoup de petits nombres + un mot-clé).
    Tri rapide avec pdfium : pdfplumber met plusieurs secondes sur une page de dessins."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return None
    out: set[int] = set()
    try:
        for i in range(len(doc)):
            text = doc[i].get_textpage().get_text_range()
            if (len(re.findall(r"(?<![\w.,])\d{1,3}(?![\w.,])", text)) >= 40
                    and re.search(r"dmx|channel|canal|mode", text, re.I)):
                out.add(i + 1)
    finally:
        doc.close()
    return out


def _fabricant(text: str) -> str:
    counts = {m: len(re.findall(rf"\b{re.escape(m)}\b", text, re.I)) for m in MAKERS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ""


def _nom(path: Path) -> str:
    stem = re.sub(r"(?i)[_\- ]*(user[_ ]?manual|manual|dmx[_ ]?chart|dmx|notice|en|fr|v\d+|rev\w*)(?=[_\- ]|$)", "",
                  Path(path).stem)
    return re.sub(r"[_\-]+", " ", stem).strip() or Path(path).stem


def lire_pdf(path: str | Path) -> Projet:
    """Projet proposé à partir de la notice. Lève `PdfError` si aucune charte n'est trouvée."""
    path = Path(path)
    grilles, text = _grilles(path)
    modes = lire_grilles(grilles)
    if not modes:
        raise PdfError(f"{path.name} : aucune charte DMX en tableau trouvée. "
                       "Tu peux saisir les canaux à la main, ou m'envoyer le PDF pour que j'adapte la lecture.")
    projet = Projet(_fabricant(text), _nom(path), "", modes)
    for m in modes:
        addrs = sorted(a for c in m.canaux for a in c.adresses)
        missing = [a for a in range(1, addrs[-1] + 1) if a not in addrs]
        if missing:
            projet.notes.append(f"{m.nom} : adresses non lues dans le PDF : {', '.join(map(str, missing[:10]))}")
    return projet
