"""Calcul du « SubfixtureOverview » de MA3 pour un mode.

Règle observée sur la console de Jo (MA3 2.3.2.0, JDC Line 1000 mode 5 JO) :
seules les géométries qui portent des canaux deviennent des sous-fixtures.
Les niveaux intermédiaires sans canal (ex. « Module A Mode 5 ») disparaissent
et leurs enfants remontent d'un cran. La racine du mode est toujours gardée.
Une référence porte les canaux de son modèle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .gdtf import DMXMode, FixtureType, Geometry


@dataclass
class Subfixture:
    name: str
    attributes: list[str]
    children: list["Subfixture"] = field(default_factory=list)


def _attrs_by_geometry(mode: DMXMode) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ch in mode.channels:
        for lc in ch.logical_channels:
            lst = out.setdefault(ch.geometry, [])
            if lc.attribute not in lst:
                lst.append(lc.attribute)
    return out


def overview(ft: FixtureType, mode: DMXMode) -> Subfixture | None:
    attrs = _attrs_by_geometry(mode)
    root = ft.top_level(mode.geometry)
    if root is None:
        return None

    def own(g: Geometry) -> list[str]:
        found = list(attrs.get(g.name, []))
        if g.is_reference:
            tpl = ft.top_level(g.reference)
            if tpl is not None:
                for x in tpl.walk():
                    found += [a for a in attrs.get(x.name, []) if a not in found]
        return found

    def build(g: Geometry) -> list[Subfixture]:
        kids = [s for c in g.children for s in build(c)]
        mine = own(g)
        if mine:
            return [Subfixture(g.name, mine, kids)]
        return kids  # niveau sans canal : fusionné dans le parent

    return Subfixture(root.name, own(root), [s for c in root.children for s in build(c)])


def lines(sub: Subfixture, index: int = 1, depth: int = 0, max_children: int = 0) -> list[str]:
    """Rendu texte proche de l'écran MA3 : « n° (enfants)  Nom  Attr1 Attr2… »."""
    num = f"{index} ({len(sub.children)})" if sub.children else f"{index}"
    out = [f"{'  ' * depth}{num:<8} {sub.name:<40} {'  '.join(sub.attributes)}"]
    for i, child in enumerate(sub.children, 1):
        if max_children and depth >= 1 and i > max_children:
            out.append(f"{'  ' * (depth + 1)}… {len(sub.children) - max_children} de plus")
            break
        out += lines(child, i, depth + 1, max_children)
    return out
