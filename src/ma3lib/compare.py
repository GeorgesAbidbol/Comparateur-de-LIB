"""Modèle d'affichage du comparateur (étape 2), sans dépendance graphique.

- `instances()` : arbre des instances d'un mode, comme le SubfixtureOverview MA3
  (1 = fixture, 1.1, 1.1.1…), avec pour chaque instance ses canaux (Coarse/Fine).
- `auto_links()` : branchement de départ des instances cible sur les instances source,
  dans l'ordre, étage par étage. Une instance cible reçoit au plus une source.
- `pair_rows()` : lignes d'attributs d'une liaison source -> cible avec leur couleur
  (vert = des deux côtés, orange = perdu / absent, jaune = remplacé, bleu = virtuel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from . import attributs
from .gdtf import DMXChannel, DMXMode, FixtureType, Geometry

GREEN, ORANGE, YELLOW, BLUE = "vert", "orange", "jaune", "bleu"


@dataclass
class Slot:
    """Un attribut porté par une instance."""
    attribute: str
    feature: str = ""
    pretty: str = ""
    addresses: list[int] = field(default_factory=list)  # [coarse, fine…], vide si virtuel

    @property
    def coarse(self) -> Optional[int]:
        return self.addresses[0] if self.addresses else None

    @property
    def fine(self) -> Optional[int]:
        return self.addresses[1] if len(self.addresses) > 1 else None

    @property
    def virtual(self) -> bool:
        return not self.addresses

    @property
    def short(self) -> str:
        return self.pretty or self.attribute


@dataclass
class Instance:
    ident: str  # « 1 », « 1.3 », « 1.3.2 »
    name: str
    slots: list[Slot] = field(default_factory=list)
    children: list["Instance"] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return self.ident.count(".")

    def walk(self) -> Iterator["Instance"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def summary(self, limit: int = 6) -> str:
        """Résumé façon Fixture Hero : « Dim RGB Strobe »."""
        names = [_short_name(s) for s in self.slots]
        out = []
        for n in names:
            if n not in out:
                out.append(n)
        text = " ".join(out[:limit])
        return text + (" …" if len(out) > limit else "")


def _short_name(slot: Slot) -> str:
    a = attributs.ma3_name(slot.attribute)
    if a.startswith("ColorRGB_") or a.startswith("ColorAdd_"):
        return "RGB" if a[-1] in "RGB" else a.split("_")[-1]
    if a.startswith("Dimmer"):
        return "Dim"
    if a.startswith("Shutter") and "Strobe" in a or a.startswith("Strobe"):
        return "Strobe"
    if a.startswith("Shutter"):
        return "Shutter"
    return slot.pretty or a


def _shift(ch: DMXChannel, ref: Geometry) -> int:
    """Décalage DMX d'un canal de modèle pour une référence (cf. charte.absolute_channels)."""
    if not ref.breaks:
        return 0
    if ch.dmx_break == "Overwrite":
        b = ref.breaks[-1]
    else:
        brk = int(ch.dmx_break) if str(ch.dmx_break).isdigit() else 1
        b = next((x for x in ref.breaks if x.dmx_break == brk), ref.breaks[0])
    return b.dmx_offset - 1


def instances(ft: FixtureType, mode: DMXMode) -> Optional[Instance]:
    """Même règle que subfixtures.overview : un niveau sans canal disparaît."""
    root = ft.top_level(mode.geometry)
    if root is None:
        return None
    by_geo: dict[str, list[DMXChannel]] = {}
    for ch in mode.channels:
        by_geo.setdefault(ch.geometry, []).append(ch)

    def slots(g: Geometry) -> list[Slot]:
        found: list[tuple[DMXChannel, int]] = [(c, 0) for c in by_geo.get(g.name, [])]
        if g.is_reference:
            tpl = ft.top_level(g.reference)
            if tpl is not None:
                for x in tpl.walk():
                    found += [(c, _shift(c, g)) for c in by_geo.get(x.name, [])]
        out = []
        for ch, shift in found:
            for lc in ch.logical_channels:
                a = ft.attributes.get(lc.attribute)
                out.append(Slot(lc.attribute, a.feature if a else "", a.pretty if a else "",
                                [o + shift for o in ch.offset] if ch.offset else []))
        return out

    def with_axes(g: Geometry) -> list[Slot]:
        # Une Axis (tête qui bascule) se fond dans l'instance du dessus : sur la console de Jo,
        # le Tilt de l'iTetra2 (Base > Axis Head) est porté par le fixture principal.
        out = slots(g)
        for c in g.children:
            if c.kind == "Axis":
                out += with_axes(c)
        return out

    def build(g: Geometry) -> list[tuple[Geometry, list[Slot], list]]:
        kids = [k for c in g.children for k in build(c)]
        if g.kind == "Axis":
            return kids
        mine = with_axes(g)
        return [(g, mine, kids)] if mine else kids

    def number(node, ident: str) -> Instance:
        g, mine, kids = node
        inst = Instance(ident, g.name, mine)
        inst.children = [number(k, f"{ident}.{i}") for i, k in enumerate(kids, 1)]
        return inst

    kids = [k for c in root.children for k in build(c)]
    return number((root, with_axes(root), kids), "1")


def flatten(root: Optional[Instance]) -> list[Instance]:
    return list(root.walk()) if root else []


def _keys(inst: Instance) -> set[str]:
    return {_key(sl.attribute) for sl in inst.slots}


def auto_links(source: Optional[Instance], target: Optional[Instance]) -> dict[str, str]:
    """{ident cible: ident source} proposé au chargement : racine sur racine, puis chaque
    instance cible (dans l'ordre) prend la première instance source libre qui partage le plus
    d'attributs. Les arbres n'ont pas besoin d'avoir la même forme (pixels à 1.1.x d'un côté,
    1.1.1.x de l'autre). Avec trop peu d'attributs communs, l'instance reste non branchée (orange)."""
    if not source or not target:
        return {}
    links = {target.ident: source.ident}
    free = [s for s in source.walk() if s is not source]
    for t in target.walk():
        if t is target or not t.slots:
            continue
        tk = _keys(t)
        best, score = None, 0.3  # au moins un tiers d'attributs en commun
        for s in free:
            sk = _keys(s)
            j = len(tk & sk) / len(tk | sk) if tk | sk else 0.0
            if j > score:
                best, score = s, j
        if best is not None:
            links[t.ident] = best.ident
            free.remove(best)
    return links


def spread(source: Instance, target: Instance) -> dict[str, str]:
    """Répartit les enfants de `source` sur ceux de `target` (ex. 20 pixels sur 12)."""
    ns, nt = len(source.children), len(target.children)
    if not ns or not nt:
        return {}
    out = {}
    for j, t in enumerate(target.children):
        i = round(j * (ns - 1) / (nt - 1)) if nt > 1 else 0
        out[t.ident] = source.children[i].ident
    return out


@dataclass
class Row:
    """Une ligne de la vue attributs : source et/ou cible, et sa couleur."""
    source: Optional[Slot]
    target: Optional[Slot]
    status: str


def _key(attr: str) -> str:
    return attributs.ma3_name(attr)


def pair_rows(source: Instance, target: Instance,
              replaced: Optional[dict[str, str]] = None,
              virtual: Optional[list[str]] = None) -> list[Row]:
    """Attributs identiques en face (vert), remplacements (jaune), virtuels (bleu),
    puis les orange : perdus côté source, absents côté cible.
    `replaced` = {attribut cible: attribut source}, `virtual` = attributs source ajoutés
    en virtuel dans la cible."""
    replaced = replaced or {}
    virtual = virtual or []
    src = {_key(s.attribute): s for s in source.slots}
    used_src: set[str] = set()
    rows: list[Row] = []
    lone_targets: list[Slot] = []
    for t in target.slots:
        k = _key(t.attribute)
        if k in src and k not in used_src:
            rows.append(Row(src[k], t, GREEN))
            used_src.add(k)
        elif t.attribute in replaced and _key(replaced[t.attribute]) in src:
            sk = _key(replaced[t.attribute])
            rows.append(Row(src[sk], t, YELLOW))
            used_src.add(sk)
        else:
            lone_targets.append(t)
    for k, s in src.items():
        if k not in used_src and s.attribute in virtual:
            rows.append(Row(s, Slot(s.attribute, s.feature, s.pretty), BLUE))
            used_src.add(k)
    rows += [Row(s, None, ORANGE) for k, s in src.items() if k not in used_src]
    rows += [Row(None, t, ORANGE) for t in lone_targets]
    return rows


def instance_status(source: Optional[Instance], target: Optional[Instance]) -> str:
    """Couleur d'une liaison : vert si aucun attribut source n'est perdu, orange sinon
    (un attribut en plus dans la cible prend simplement sa valeur par défaut)."""
    if source is None or target is None:
        return ORANGE
    lost = any(r.target is None for r in pair_rows(source, target))
    return ORANGE if lost else GREEN
