"""Réorganisation de l'arbre des géométries (étape 3, atelier).

`move()` déplace une ou plusieurs géométries sous un nouveau parent, à une position donnée,
à la fois dans le modèle (`Geometry`) et dans l'arbre XML d'origine (`ft.xml_root`), pour
que l'écriture du fichier garde tout le reste intact.

Les canaux suivent leur géométrie :
- GDTF : un canal désigne sa géométrie par son nom seul, rien à changer ;
- XML MA3 : un canal désigne sa géométrie par un chemin pointé (`Base.Body.Plate`),
  on réécrit les chemins de tout le sous-arbre déplacé.
Les relations MA3 désignent des canaux par nom (`Geometrie_Attribut`), pas par chemin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import xml.etree.ElementTree as ET

from .gdtf import GEOMETRY_TAGS, FixtureType, Geometry


class MoveError(Exception):
    """Déplacement impossible (expliqué en clair)."""


@dataclass
class Undo:
    """De quoi annuler un déplacement : chaque géométrie retourne à sa place d'avant."""
    places: list[tuple[Geometry, Geometry, int]]  # (géométrie, ancien parent, ancien rang)


def names_path(g: Geometry) -> list[str]:
    out, node = [], g
    while node is not None:
        out.append(node.name)
        node = node.parent
    return list(reversed(out))


def element_of(ft: FixtureType, g: Geometry) -> Optional[ET.Element]:
    """Élément XML de la géométrie, retrouvé par son chemin de noms depuis <Geometries>."""
    if ft.xml_root is None:
        return None
    node = ft.xml_root.find("FixtureType/Geometries")
    for name in names_path(g):
        if node is None:
            return None
        node = next((c for c in node if c.tag in GEOMETRY_TAGS and c.get("Name") == name), None)
    return node


def check(g: Geometry, new_parent: Geometry) -> Optional[str]:
    """Raison pour laquelle `g` ne peut pas aller sous `new_parent`, ou None."""
    if g.parent is None:
        return f"« {g.name} » est une racine (mode ou modèle) : elle ne se déplace pas"
    if new_parent.is_reference:
        return f"« {new_parent.name} » est une référence : elle ne peut pas avoir d'enfant"
    node = new_parent
    while node is not None:
        if node is g:
            return f"« {g.name} » ne peut pas aller dans sa propre descendance"
        node = node.parent
    return None


def move(ft: FixtureType, geos: list[Geometry], new_parent: Geometry, index: int) -> Undo:
    """Place `geos` (dans cet ordre) sous `new_parent`, à partir du rang `index`
    (rang compté parmi les enfants de `new_parent` avant le déplacement)."""
    for g in geos:
        reason = check(g, new_parent)
        if reason:
            raise MoveError(reason)
    # les géométries déjà sous ce parent et placées avant le rang visé décalent le rang
    index -= sum(1 for g in geos if g.parent is new_parent and new_parent.children.index(g) < index)
    undo = Undo([(g, g.parent, g.parent.children.index(g)) for g in geos])
    old_paths = {id(g): ".".join(names_path(g)) for g in geos}

    parent_el = element_of(ft, new_parent)
    els = [element_of(ft, g) for g in geos]
    for g, el in zip(geos, els):
        old_parent_el = element_of(ft, g.parent)
        g.parent.children.remove(g)
        if el is not None and old_parent_el is not None:
            old_parent_el.remove(el)
    index = max(0, min(index, len(new_parent.children)))
    for k, (g, el) in enumerate(zip(geos, els)):
        new_parent.children.insert(index + k, g)
        g.parent = new_parent
        if el is not None and parent_el is not None:
            _insert_xml(parent_el, el, new_parent, index + k)

    if ft.format == "ma3":
        _rewrite_paths(ft, {old_paths[id(g)]: ".".join(names_path(g)) for g in geos})
    return undo


def undo(ft: FixtureType, u: Undo) -> None:
    """Remet chaque géométrie à son ancien rang, du plus petit au plus grand."""
    for g, parent, idx in sorted(u.places, key=lambda p: p[2]):
        # `move` compte le rang avec la géométrie encore en place : on compense si elle est
        # déjà sous ce parent, avant le rang visé
        before = g.parent is parent and parent.children.index(g) < idx
        move(ft, [g], parent, idx + 1 if before else idx)


def _insert_xml(parent_el: ET.Element, el: ET.Element, parent: Geometry, rank: int) -> None:
    """Insère l'élément au même rang que dans le modèle, parmi les enfants géométries
    (d'autres balises, ex. <Break>, peuvent être mêlées : on se cale sur les géométries)."""
    geo_children = [c for c in parent_el if c.tag in GEOMETRY_TAGS]
    if rank < len(geo_children):
        parent_el.insert(list(parent_el).index(geo_children[rank]), el)
    else:
        parent_el.append(el)


def _rewrite_paths(ft: FixtureType, renames: dict[str, str]) -> None:
    def new_path(path: str) -> str:
        for old, new in renames.items():
            if path == old or path.startswith(old + "."):
                return new + path[len(old):]
        return path

    if ft.xml_root is not None:
        for ch in ft.xml_root.iter("DMXChannel"):
            geo = ch.get("Geometry", "")
            if "." in geo:
                ch.set("Geometry", new_path(geo))
    for mode in ft.modes:
        for ch in mode.channels:
            if ch.geometry_path:
                ch.geometry_path = new_path(ch.geometry_path)
