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


# --------------------------------------------------------------------------
# A. Regrouper des géométries identiques en un modèle + des références
#
# Règle de Jo : dès qu'un même type d'instance se répète (masters A/B, 12 têtes, pixels),
# on décrit une seule fois le modèle et on le pose N fois par des références, chacune avec
# son adresse (Break). La référence garde le nom et la position de la géométrie qu'elle
# remplace : la console voit les mêmes instances, aux mêmes adresses.

def snapshot(ft: FixtureType) -> bytes:
    """Copie de l'XML, pour annuler une opération en le relisant."""
    return ET.tostring(ft.xml_root, encoding="utf-8")


def restore(ft: FixtureType, data: bytes) -> FixtureType:
    from .gdtf import parse_description
    new = parse_description(data)
    new.source = ft.source
    return new


@dataclass
class _Plan:
    """Ce que le regroupement va écrire, calculé et vérifié avant de toucher à quoi que ce soit."""
    bases: list[int]  # adresse (DMXOffset) de chaque référence
    dmx_break: int
    renames: dict[str, str]  # ancien nom de canal -> nom du canal du modèle
    message: str
    # 2e jeu d'adresses (méthode iTetra2) : un 2e Break par référence, que les modes listés
    # ici prennent avec des canaux en DMXBreak="Overwrite"
    bases2: Optional[list[int]] = None
    overwrite_modes: Optional[set[str]] = None


def _carries_channels(ft: FixtureType, model: str) -> bool:
    tpl = ft.top_level(model)
    names = {x.name for x in tpl.walk()} if tpl else {model}
    return any(c.geometry in names for m in ft.modes for c in m.channels)


def _inline_references(ft: FixtureType, el: ET.Element) -> None:
    """Dans un modèle, remplace chaque référence (visuelle) par une copie de son modèle."""
    import copy
    for parent in list(el.iter()):
        for i, child in enumerate(list(parent)):
            if child.tag != "GeometryReference":
                continue
            tpl = element_of(ft, ft.top_level(child.get("Geometry", "")))
            if tpl is None:
                continue
            inline = copy.deepcopy(tpl)
            inline.set("Name", child.get("Name", ""))
            for k in ("Position", "Model"):
                if child.get(k):
                    inline.set(k, child.get(k))
            inline.tail = child.tail
            parent.remove(child)
            parent.insert(i, inline)


def _subtree(g: Geometry) -> list[Geometry]:
    return list(g.walk())


def plan_group(ft: FixtureType, geos: list[Geometry], model_name: str) -> _Plan:
    """Vérifie qu'on peut regrouper `geos` et calcule les adresses. Lève MoveError sinon."""
    from .diagnostic import _signature  # même empreinte que le diagnostic (numéros ignorés)

    if ft.format != "gdtf":
        raise MoveError("regrouper n'est fait pour l'instant que sur un GDTF (pas encore sur un XML MA3)")
    if len(geos) < 2:
        raise MoveError("il faut au moins deux géométries identiques")
    if not model_name or ft.geometry(model_name) is not None:
        raise MoveError(f"le nom de modèle « {model_name} » est vide ou déjà pris")
    for g in geos:
        if g.parent is None:
            raise MoveError(f"« {g.name} » est une racine : on regroupe des géométries de l'arbre")
        if g.is_reference:
            raise MoveError(f"« {g.name} » est déjà une référence")
        for x in g.walk():
            # une référence dans une référence n'existe pas : on n'accepte que les références
            # « visuelles » (modèle sans canal, ex. Color Strike M), recopiées dans le modèle
            if x.is_reference and _carries_channels(ft, x.reference):
                raise MoveError(f"« {g.name} » contient la référence « {x.name} » qui porte des canaux")
    if len({_signature(g) for g in geos}) > 1:
        raise MoveError("ces géométries n'ont pas la même structure (types ou enfants différents)")

    trees = [_subtree(g) for g in geos]
    sets: list[list[int]] = []  # jeux d'adresses distincts
    set_of_mode: dict[str, int] = {}
    dmx_break = 1
    renames: dict[str, str] = {}
    used_modes = 0
    for mode in ft.modes:
        per_geo = []
        for tree in trees:
            index = {x.name: i for i, x in enumerate(tree)}
            chans = [(index[c.geometry], c) for c in mode.channels if c.geometry in index]
            per_geo.append(chans)
        if not any(per_geo):
            continue
        used_modes += 1
        if not all(per_geo):
            raise MoveError(f"mode « {mode.name} » : certaines de ces géométries n'ont pas de canaux")
        sigs, mode_bases = [], []
        for chans in per_geo:
            real = [c.offset[0] for _, c in chans if c.offset]
            base = min(real) if real else 1
            brks = {c.dmx_break for _, c in chans if c.offset}
            if len(brks) > 1 or brks & {"Overwrite"}:
                raise MoveError(f"mode « {mode.name} » : canaux sur plusieurs breaks, pas encore géré")
            if brks:
                dmx_break = int(next(iter(brks)))
            sigs.append(sorted((i, tuple(lc.attribute for lc in c.logical_channels),
                                tuple(o - base for o in c.offset) if c.offset else None)
                               for i, c in chans))
            mode_bases.append(base)
        if any(s != sigs[0] for s in sigs):
            raise MoveError(f"mode « {mode.name} » : ces géométries n'ont pas les mêmes canaux "
                            "(attributs ou écarts d'adresses différents)")
        if mode_bases not in sets:
            sets.append(mode_bases)
        set_of_mode[mode.name] = sets.index(mode_bases)
        if len(sets) > 2:
            raise MoveError("adresses différentes dans plus de deux modes pour le même arbre : "
                            "une référence ne porte que deux jeux d'adresses (méthode iTetra2). "
                            "Il faut d'abord séparer l'arbre par mode")
        for tree, chans in zip(trees, per_geo):
            for i, c in chans:
                new_geo = model_name if i == 0 else trees[0][i].name
                renames[f"{tree[i].name}_{c.attribute}"] = f"{new_geo}_{c.attribute}"
    if not sets:
        raise MoveError("aucun canal sur ces géométries : rien à regrouper (3D seule ?)")
    bases = sets[0]
    msg = (f"{len(geos)} géométries → modèle « {model_name} » + {len(geos)} références "
           f"(adresses {', '.join(str(b) for b in bases[:6])}{'…' if len(bases) > 6 else ''})")
    if len(sets) == 2:
        msg += " ; 2 jeux d'adresses selon le mode"
        return _Plan(bases, dmx_break, renames, msg, sets[1],
                     {m for m, i in set_of_mode.items() if i == 1})
    return _Plan(bases, dmx_break, renames, msg)


def group(ft: FixtureType, geos: list[Geometry], model_name: str) -> tuple[FixtureType, str]:
    """Remplace `geos` par des références vers un nouveau modèle de premier niveau.
    Renvoie le fixture relu depuis l'XML modifié, et un message pour l'écran."""
    import copy

    plan = plan_group(ft, geos, model_name)
    trees = [_subtree(g) for g in geos]
    first_names = {x.name for x in trees[0]}
    all_names = {x.name for t in trees for x in t}
    root_xml = ft.xml_root
    node = root_xml.find("FixtureType")

    # 1. le modèle : copie de la première géométrie, au premier niveau
    first_el = element_of(ft, geos[0])
    model_el = copy.deepcopy(first_el)
    model_el.set("Name", model_name)
    model_el.attrib.pop("Position", None)  # la position reste sur chaque référence
    _inline_references(ft, model_el)
    node.find("Geometries").append(model_el)

    # 2. chaque géométrie devient une référence (même nom, même position, même rang)
    for k, (g, base) in enumerate(zip(geos, plan.bases)):
        el = element_of(ft, g)
        parent_el = element_of(ft, g.parent)
        ref = ET.Element("GeometryReference", {k: v for k, v in el.attrib.items()
                                               if k in ("Name", "Position", "Model")})
        ref.set("Geometry", model_name)
        ET.SubElement(ref, "Break", {"DMXOffset": str(base), "DMXBreak": str(plan.dmx_break)})
        if plan.bases2:
            ET.SubElement(ref, "Break", {"DMXOffset": str(plan.bases2[k]), "DMXBreak": str(plan.dmx_break)})
        ref.tail = el.tail
        i = list(parent_el).index(el)
        parent_el.remove(el)
        parent_el.insert(i, ref)

    # 3. les canaux : ceux de la première géométrie passent sur le modèle en adresses
    #    relatives, ceux des copies disparaissent (le modèle les porte pour toutes)
    for mode_el in node.iterfind("DMXModes/DMXMode"):
        chans_el = mode_el.find("DMXChannels")
        if chans_el is None:
            continue
        second = plan.overwrite_modes and mode_el.get("Name") in plan.overwrite_modes
        base0 = plan.bases2[0] if second else plan.bases[0]
        for ch in list(chans_el):
            geo = ch.get("Geometry", "")
            if geo not in all_names:
                continue
            if geo not in first_names:
                chans_el.remove(ch)
                continue
            if geo == geos[0].name:
                ch.set("Geometry", model_name)
            off = (ch.get("Offset") or "None").strip()
            if off not in ("None", ""):
                ch.set("Offset", ",".join(str(int(o) - base0 + 1) for o in off.split(",")))
                if second:
                    ch.set("DMXBreak", "Overwrite")
        # liens (InitialFunction, relations…) : vers les canaux du modèle, sans doublons
        from .remap import LINK_ATTRS
        for el in mode_el.iter():
            for key in LINK_ATTRS:
                v = el.get(key)
                if v and v.split(".")[0] in plan.renames:
                    segs = v.split(".")
                    segs[0] = plan.renames[segs[0]]
                    el.set(key, ".".join(segs))
        rel_el = mode_el.find("Relations")
        if rel_el is not None:
            seen = set()
            for r in list(rel_el):
                key = (r.get("Master"), r.get("Follower"), r.get("Type"))
                if key in seen:
                    rel_el.remove(r)
                seen.add(key)
    return restore(ft, ET.tostring(root_xml, encoding="utf-8")), plan.message


def suggested_model_name(ft: FixtureType, geos: list[Geometry]) -> str:
    """Nom proposé : la partie commune des noms (« Head 1 », « Head 2 » -> « Head »)."""
    import re
    stem = re.sub(r"[\s_\-]*[\d/]+\s*$", "", geos[0].name).strip() or geos[0].name
    name, n = stem, 2
    while ft.geometry(name) is not None:
        name, n = f"{stem} modèle" if n == 2 else f"{stem} modèle {n}", n + 1
    return name


def plan_merge(ft: FixtureType, models: list[Geometry]) -> dict[str, str]:
    """Modèles en double d'un mode à l'autre (JDC : « … Mode 3 », « … Mode 5 ») : vérifie qu'on
    peut tous les remplacer par le premier. Renvoie {ancien nom de géométrie: nouveau}."""
    from .diagnostic import _signature
    if ft.format != "gdtf":
        raise MoveError("fusionner n'est fait pour l'instant que sur un GDTF (pas encore sur un XML MA3)")
    if len(models) < 2 or any(m.parent is not None for m in models):
        raise MoveError("il faut au moins deux modèles (géométries de premier niveau)")
    if len({_signature(m) for m in models}) > 1:
        raise MoveError("ces modèles n'ont pas la même structure")
    mode_roots = {m.geometry for m in ft.modes}
    if any(m.name in mode_roots for m in models):
        raise MoveError("ce sont des racines de mode, pas des modèles référencés")
    users = []
    for m in models:
        names = {x.name for x in m.walk()}
        users.append({mode.name for mode in ft.modes if any(c.geometry in names for c in mode.channels)})
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            both = users[i] & users[j]
            if both:
                raise MoveError(f"« {models[i].name} » et « {models[j].name} » servent tous les deux "
                                f"dans « {sorted(both)[0]} » : ce sont deux instances voulues, pas un doublon")
    keep = list(models[0].walk())
    renames = {}
    for m in models[1:]:
        for a, b in zip(m.walk(), keep):
            renames[a.name] = b.name
    return renames


def merge_models(ft: FixtureType, models: list[Geometry]) -> tuple[FixtureType, str]:
    """Garde le premier modèle, fait pointer toutes les références des autres vers lui
    (canaux compris) et retire les modèles devenus inutiles."""
    from .remap import LINK_ATTRS
    renames = plan_merge(ft, models)
    node = ft.xml_root.find("FixtureType")
    gone = {m.name for m in models[1:]}
    for el in node.iter("GeometryReference"):
        if el.get("Geometry") in gone:
            el.set("Geometry", models[0].name)
    for mode_el in node.iterfind("DMXModes/DMXMode"):
        chan_renames = {}
        for ch in mode_el.iterfind("DMXChannels/DMXChannel"):
            geo = ch.get("Geometry", "")
            if geo in renames:
                ch.set("Geometry", renames[geo])
                lc = ch.find("LogicalChannel")
                attr = lc.get("Attribute", "").split(".")[-1] if lc is not None else ""
                chan_renames[f"{geo}_{attr}"] = f"{renames[geo]}_{attr}"
        for el in mode_el.iter():
            for key in LINK_ATTRS:
                v = el.get(key)
                if v and v.split(".")[0] in chan_renames:
                    segs = v.split(".")
                    segs[0] = chan_renames[segs[0]]
                    el.set(key, ".".join(segs))
    geos_el = node.find("Geometries")
    for m in models[1:]:
        geos_el.remove(element_of(ft, m))
    msg = f"{len(models)} modèles fusionnés en « {models[0].name} »"
    return restore(ft, ET.tostring(ft.xml_root, encoding="utf-8")), msg


# --------------------------------------------------------------------------
# B. Dupliquer une référence N fois, à adresses contiguës

def _break_users(ft: FixtureType, ref: Geometry) -> list[list[tuple[str, list[int]]]]:
    """Pour chaque Break de la référence : les canaux du modèle qui le prennent, par mode
    (règle de la spec : DMXBreak = n -> le Break n ; « Overwrite » -> le dernier)."""
    tpl = ft.top_level(ref.reference)
    names = {x.name for x in tpl.walk()} if tpl else set()
    users: list[list[tuple[str, list[int]]]] = [[] for _ in ref.breaks]
    if not ref.breaks:
        return users
    mode_has_ref = {m.name for m in ft.modes
                    if (root := ft.top_level(m.geometry)) and any(x is ref for x in root.walk())}
    for m in ft.modes:
        if m.name not in mode_has_ref:
            continue
        for c in m.channels:
            if c.geometry not in names or not c.offset:
                continue
            if c.dmx_break == "Overwrite":
                j = len(ref.breaks) - 1
            else:
                brk = int(c.dmx_break) if str(c.dmx_break).isdigit() else 1
                j = next((i for i, b in enumerate(ref.breaks) if b.dmx_break == brk), 0)
            users[j].append((m.name, c.offset))
    return users


def duplicate_steps(ft: FixtureType, ref: Geometry) -> list[int]:
    """Pas proposé pour chaque Break : la place que prend le modèle (4 en RGBW, 3 en RGB)."""
    out = []
    for users in _break_users(ft, ref):
        by_mode: dict[str, list[int]] = {}
        for mode, offs in users:
            by_mode.setdefault(mode, []).extend(offs)
        # étendue des adresses du modèle dans chaque mode (les offsets du modèle ne
        # commencent pas forcément à 1 : 57…60 sur l'iTetra2 -> pas de 4)
        out.append(max((max(v) - min(v) + 1 for v in by_mode.values()), default=1))
    return out


def _next_names(ft: FixtureType, name: str, n: int) -> list[str]:
    import re
    m = re.search(r"(\d+)(\D*)$", name)
    taken = {g.name for g in ft.all_geometries()}
    out, k = [], 1
    while len(out) < n:
        if m:
            num = int(m.group(1)) + k
            cand = f"{name[:m.start(1)]}{num:0{len(m.group(1))}d}{m.group(2)}"
        else:
            cand = f"{name} {k + 1}"
        if cand not in taken:
            out.append(cand)
            taken.add(cand)
        k += 1
    return out


def duplicate(ft: FixtureType, ref: Geometry, count: int,
              steps: Optional[list[int]] = None) -> tuple[FixtureType, str]:
    """Ajoute `count` copies de la référence juste après elle, chacune décalée du pas
    (un pas par Break). Les canaux du modèle s'appliquent tout seuls aux nouvelles références."""
    import copy
    if not ref.is_reference:
        raise MoveError(f"« {ref.name} » n'est pas une référence : regroupe d'abord en modèle + références")
    if ref.parent is None:
        raise MoveError("une référence de premier niveau ne se duplique pas")
    if count < 1:
        raise MoveError("nombre de copies : au moins 1")
    steps = steps or duplicate_steps(ft, ref)
    if len(steps) != len(ref.breaks):
        raise MoveError("il faut un pas par Break de la référence")
    el = element_of(ft, ref)
    parent_el = element_of(ft, ref.parent)
    pos = list(parent_el).index(el)
    names = _next_names(ft, ref.name, count)
    for k, name in enumerate(names, 1):
        new = copy.deepcopy(el)
        new.set("Name", name)
        for b_el, step in zip(new.iterfind("Break"), steps):
            off = int(b_el.get("DMXOffset") or b_el.get("DMXPatch") or 1) + k * step
            b_el.set("DMXPatch" if b_el.get("DMXPatch") is not None else "DMXOffset", str(off))
        parent_el.insert(pos + k, new)
    new_ft = restore(ft, ET.tostring(ft.xml_root, encoding="utf-8"))
    msg = f"« {ref.name} » dupliquée {count} fois ({names[0]} … {names[-1]}, pas {'/'.join(map(str, steps))})"
    clash = _overlaps(new_ft, set(names))
    if clash:
        msg += f" — attention, adresses déjà prises : {clash}"
    return new_ft, msg


def _overlaps(ft: FixtureType, new_names: set[str]) -> str:
    """Modes où les nouvelles instances tombent sur des adresses déjà utilisées."""
    from .compare import flatten, instances
    out = []
    for m in ft.modes:
        used: dict[int, str] = {}
        clash = set()
        for inst in flatten(instances(ft, m)):
            for s in inst.slots:
                for a in s.addresses:
                    if a in used and (inst.name in new_names) != (used[a] in new_names):
                        clash.add(a)
                    used.setdefault(a, inst.name)
        if clash:
            out.append(f"{m.name} (canal {min(clash)}…)")
    return ", ".join(out[:3])
