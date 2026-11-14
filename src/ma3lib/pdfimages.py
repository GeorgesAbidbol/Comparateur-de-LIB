"""Images des roues (gobos, couleurs) d'une notice PDF -> emplacements des roues du `Projet`.

Sur les pages qui parlent de gobos ou de roue de couleurs, on prend les images à peu près carrées
et on les rattache aux emplacements :
- par le texte le plus proche de l'image (le nom de l'emplacement, ou son numéro : « Gobo 3 », « 3 ») ;
- sinon dans l'ordre de lecture, quand il y a autant d'images que d'emplacements (hors « Open »).
Le titre au-dessus des images (« Rotating gobo wheel », « Static gobos »…) désigne la roue.

Seules les vraies images sont lues ; un dessin vectoriel (traits du PDF) n'en est pas une.
C'est une proposition : chaque image se remplace ou se retire dans l'onglet « Créer ».
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from .creation import Projet, canaux_de_roue, roues

_PAGE = re.compile(r"gobo|\bwheels?\b|roue", re.I)
_TITRE = re.compile(r"gobo|colou?r|wheel|roue|animation", re.I)
_ENTETE = re.compile(r"wheel|roue|gobos\b", re.I)  # une ligne de titre n'est jamais le nom d'un emplacement
_OUVERT = re.compile(r"^(open|white|ouvert|blanc|no gobo|empty)\b", re.I)
_BANAL = {"wheel", "wheels", "gobo", "gobos", "color", "colour", "colors", "colours", "roue", "figure", "with",
          "rotating", "static", "fixed", "animation", "standard", "slot", "slots"}
MAX_PAGES = 15
COTE = 256  # côté maximal de l'image gardée, en pixels


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _numero(text: str) -> str:
    m = re.search(r"(\d+)\s*$", text.strip())
    return m.group(1) if m else ""


def _pages(path: Path) -> list[int]:
    """Numéros (à partir de 1) des pages qui parlent de roues, avec pdfium (rapide)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    try:
        out = []
        for i in range(len(doc)):
            text = doc[i].get_textpage().get_text_range()
            # (une page couverte de petits nombres est une charte DMX, pas une planche de gobos)
            if _PAGE.search(text) and len(re.findall(r"(?<![\w.,])\d{1,3}(?![\w.,])", text)) < 40:
                out.append(i + 1)
        return out
    finally:
        doc.close()


def _dist(word: dict, im: dict) -> float:
    x, y = (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2
    dx = max(im["x0"] - x, 0, x - im["x1"])
    dy = max(im["top"] - y, 0, y - im["bottom"])
    return (dx * dx + dy * dy) ** 0.5


def _lignes(words: list[dict]) -> list[tuple[float, str]]:
    """(haut, texte) des lignes de la page."""
    rows: dict[int, list[dict]] = {}
    for w in words:
        rows.setdefault(round(w["top"] / 3), []).append(w)
    return sorted((min(w["top"] for w in ws), " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])))
                  for ws in rows.values())


def choisir_roue(titre: str, noms: dict[str, str]) -> str:
    """Roue désignée par un titre de la notice, parmi `noms` (roue -> noms de ses canaux)."""
    t = titre.lower()
    gobo, couleur = "gobo" in t or "animation" in t, bool(re.search(r"colou?r|couleur", t))
    best, best_score = "", -99
    for wheel, names in noms.items():
        n = names.lower()
        if wheel.startswith("Color") and gobo and not couleur or wheel.startswith("Gobo") and couleur and not gobo:
            continue
        score = 0
        for flag in (r"rotat|tourn", r"static|fixed|fixe", r"animation"):
            a, b = bool(re.search(flag, t)), bool(re.search(flag, n))
            score += 2 if a and b else -1 if a != b else 0
        nums = set(re.findall(r"\d+", t))
        if nums:
            score += 2 if nums & set(re.findall(r"\d+", n + " " + wheel)) else -1
        # un mot propre à la roue : « Breakup wheel » pour « Breakup wheel (wheel 1): gobo selection… »
        score += 3 * sum(1 for w in set(re.findall(r"[a-z]{4,}", t)) - _BANAL if re.search(rf"\b{w}\b", n))
        if score > best_score:
            best, best_score = wheel, score
    return best


def rattacher(images: list[dict], slots: list[str]) -> dict[str, dict]:
    """Emplacement -> image. `images` : dictionnaires avec « label » (texte voisin), dans l'ordre de lecture."""
    out: dict[str, dict] = {}
    left = list(images)
    for slot in sorted(slots, key=len, reverse=True):  # « Gobo 12 » avant « Gobo 1 »
        name, num = _norm(slot), _numero(slot)
        for im in left:
            label = _norm(im["label"])
            if not label:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![0-9])", label) or (
                    num and len(label.split()) <= 3 and num in label.split()):
                out[slot] = im
                left.remove(im)
                break
    free = [s for s in slots if s not in out and not _OUVERT.match(s.strip())]
    if left and len(left) == len(free):
        out.update(zip(free, left))
    return out


def _png(page, im: dict, gobo: bool = False) -> bytes:
    box = (max(im["x0"], page.bbox[0]), max(im["top"], page.bbox[1]),
           min(im["x1"], page.bbox[2]), min(im["bottom"], page.bbox[3]))
    picture = page.crop(box).to_image(resolution=300).original.convert("RGB")
    if gobo:
        picture = _sur_noir(picture)
    picture.thumbnail((COTE, COTE))
    buf = io.BytesIO()
    picture.save(buf, "PNG")
    return buf.getvalue()


def _sur_noir(picture):
    """Gobo dessiné sur le blanc de la page : le papier autour devient noir (dans la console, le blanc
    est la lumière qui passe), puis l'image est recadrée au carré sur le gobo."""
    from PIL import Image, ImageChops, ImageDraw
    out = picture.copy()
    w, h = out.size
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if min(out.getpixel(xy)) > 200:
            ImageDraw.floodfill(out, xy, (0, 0, 0), thresh=90)
    if out.convert("L").point(lambda v: 255 if v > 40 else 0).getbbox() is None:
        return picture  # dessin noir sur blanc sans disque : on le laisse tel quel
    # le gobo = tout ce qui n'était pas du papier (clair avant, noir après le remplissage)
    paper = ImageChops.multiply(picture.convert("L").point(lambda v: 255 if v > 200 else 0),
                                out.convert("L").point(lambda v: 255 if v < 40 else 0))
    box = ImageChops.invert(paper).getbbox()
    if box is None or (box[2] - box[0]) * (box[3] - box[1]) < 0.03 * w * h:
        return picture
    out = out.crop(box)
    side = max(out.size)
    square = Image.new("RGB", (side, side), (0, 0, 0))
    square.paste(out, ((side - out.width) // 2, (side - out.height) // 2))
    return square


def _figures(page, words: list[dict]) -> list[dict]:
    """Dessins repérés par une rangée de numéros (« 1 2 3 4 5 » sous cinq gobos) : un carré au-dessus de
    chaque numéro, large comme l'écart entre deux numéros. Vrais dessins seulement (traits ou image dedans)."""
    rows: dict[int, list[dict]] = {}
    for w in words:
        if re.fullmatch(r"\d{1,2}", w["text"]):
            rows.setdefault(round(w["top"] / 3), []).append(w)
    marks = [(o["x0"], o["top"], o["x1"], o["bottom"]) for o in list(page.curves) + list(page.images) + list(page.rects)]
    out: list[dict] = []
    for ws in rows.values():
        ws.sort(key=lambda w: w["x0"])
        nums = [int(w["text"]) for w in ws]
        if len(ws) < 3 or nums != list(range(nums[0], nums[0] + len(ws))):
            continue
        centers = [(w["x0"] + w["x1"]) / 2 for w in ws]
        steps = [b - a for a, b in zip(centers, centers[1:])]
        step = sorted(steps)[len(steps) // 2]
        if step < 24 or max(steps) - min(steps) > 0.15 * step:
            continue
        bottom = min(w["top"] for w in ws) - 1
        for w, cx in zip(ws, centers):
            box = {"x0": cx - step / 2, "x1": cx + step / 2, "top": bottom - step, "bottom": bottom,
                   "label": w["text"], "figure": True}
            inside = sum(1 for x0, top, x1, b in marks
                         if x0 >= box["x0"] - 2 and x1 <= box["x1"] + 2 and top >= box["top"] - 2 and b <= box["bottom"] + 2)
            if inside:
                out.append(box)
    return out


def images_des_roues(path: str | Path, projet: Projet) -> int:
    """Range dans `projet.images` les images de roues trouvées dans le PDF ; renvoie leur nombre."""
    wheels = roues(projet)
    if not wheels:
        return 0
    noms = canaux_de_roue(projet)
    import pdfplumber
    count = 0
    with pdfplumber.open(str(path)) as pdf:
        for number in _pages(Path(path))[:MAX_PAGES]:
            page = pdf.pages[number - 1]
            words = page.extract_words()
            figures = _figures(page, words)
            seen, images = set(), []
            for im in page.images:
                w, h = im["x1"] - im["x0"], im["bottom"] - im["top"]
                key = (round(im["x0"]), round(im["top"]), round(w), round(h))
                if w < 18 or h < 18 or not 0.6 <= w / h <= 1.7 or w > 0.45 * page.width or key in seen:
                    continue
                if any(f["x0"] <= (im["x0"] + im["x1"]) / 2 <= f["x1"] and f["top"] <= (im["top"] + im["bottom"]) / 2
                       <= f["bottom"] for f in figures):
                    continue  # déjà dans un dessin numéroté
                seen.add(key)
                images.append({"x0": im["x0"], "x1": im["x1"], "top": im["top"], "bottom": im["bottom"], "label": ""})
            if not images and not figures:
                continue
            heads = {round(top / 3) for top, text in _lignes(words) if _ENTETE.search(text)}
            free = []
            for w in words:  # chaque mot va à l'image la plus proche, si elle est vraiment à côté
                im = min(images, key=lambda i: _dist(w, i)) if images else None
                if im is not None and round(w["top"] / 3) not in heads \
                        and _dist(w, im) <= max(14.0, 0.35 * (im["bottom"] - im["top"])):
                    im["label"] += " " + w["text"]
                else:
                    free.append(w)
            titles = [(top, text) for top, text in _lignes(free) if _TITRE.search(text) and len(text) < 80]
            groups: dict[str, list[dict]] = {}
            for im in images + figures:
                above = [text for top, text in titles if top < im["top"] + 2]
                wheel = choisir_roue(above[-1] if above else (page.extract_text() or "")[:300], noms)
                named = sum(1 for s in wheels.get(wheel, []) if re.search(
                    rf"(?<![a-z0-9]){re.escape(_norm(s))}(?![0-9])", _norm(im["label"])))
                if wheel and named < 2:  # plusieurs noms autour d'une image : la roue entière, pas un emplacement
                    groups.setdefault(wheel, []).append(im)
            for wheel, ims in groups.items():
                height = min(i["bottom"] - i["top"] for i in ims)
                ims.sort(key=lambda i: (round(i["top"] / max(height / 2, 1)), i["x0"]))
                found = rattacher(ims, [s for s in wheels[wheel] if not projet.image(wheel, s)])
                for slot, im in found.items():
                    projet.definir_image(wheel, slot, _png(page, im, gobo=not wheel.startswith("Color")))
                count += len(found)
                if len(found) < len(ims):
                    projet.notes.append(f"page {number} : {len(ims) - len(found)} image(s) de « {wheel} » non "
                                        "rattachée(s) à un emplacement, à placer à la main")
    return count
