"""Lecture d'un fichier GDTF (archive zip contenant description.xml).

On ne garde que ce qui sert au comparateur et à l'atelier géométries :
attributs, géométries (arbre complet), modes DMX, canaux et relations.
L'arbre XML d'origine est conservé (`FixtureType.xml_root`) pour pouvoir
réécrire le fichier plus tard sans rien perdre.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional
import xml.etree.ElementTree as ET

# Types de géométrie définis par la spec GDTF 1.2 (table 34).
GEOMETRY_TAGS = {
    "Geometry", "Axis", "FilterBeam", "FilterColor", "FilterGobo", "FilterShaper",
    "Beam", "MediaServerLayer", "MediaServerCamera", "MediaServerMaster", "Display",
    "GeometryReference", "Laser", "WiringObject", "Inventory", "Structure",
    "Support", "Magnet",
}


class GdtfError(Exception):
    """Fichier GDTF illisible ou incomplet."""


@dataclass
class Attribute:
    name: str
    pretty: str = ""
    feature: str = ""  # ex. "Dimmer.Dimmer", "Color.RGB"
    activation_group: str = ""


@dataclass
class Break:
    dmx_offset: int
    dmx_break: int


@dataclass
class Geometry:
    name: str
    kind: str  # balise XML : Geometry, Axis, Beam, GeometryReference...
    model: str = ""
    position: str = ""
    reference: str = ""  # pour GeometryReference : géométrie référencée
    breaks: list[Break] = field(default_factory=list)
    children: list["Geometry"] = field(default_factory=list)
    parent: Optional["Geometry"] = field(default=None, repr=False, compare=False)

    @property
    def is_reference(self) -> bool:
        return self.kind == "GeometryReference"

    def walk(self) -> Iterator["Geometry"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def path(self) -> str:
        parts, node = [], self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return " / ".join(reversed(parts))


@dataclass
class ChannelFunction:
    name: str
    attribute: str
    dmx_from: str = "0/1"
    default: str = ""


@dataclass
class LogicalChannel:
    attribute: str
    functions: list[ChannelFunction] = field(default_factory=list)


@dataclass
class DMXChannel:
    geometry: str
    offset: Optional[list[int]]  # None = canal virtuel (pas d'adresse DMX)
    dmx_break: str = "1"
    logical_channels: list[LogicalChannel] = field(default_factory=list)

    @property
    def attribute(self) -> str:
        """Attribut du premier canal logique (sert au nom du canal)."""
        return self.logical_channels[0].attribute if self.logical_channels else ""

    @property
    def name(self) -> str:
        return f"{self.geometry}_{self.attribute}"

    @property
    def is_virtual(self) -> bool:
        return self.offset is None

    @property
    def resolution(self) -> int:
        """Nombre d'octets (1 = 8 bits, 2 = 16 bits...)."""
        return len(self.offset) if self.offset else 0


@dataclass
class Relation:
    name: str
    master: str
    follower: str
    type: str


@dataclass
class DMXMode:
    name: str
    geometry: str
    description: str = ""
    channels: list[DMXChannel] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    @property
    def footprint(self) -> int:
        """Nombre de canaux DMX occupés pour le break 1 (hors références)."""
        used = set()
        for ch in self.channels:
            if ch.offset and ch.dmx_break in ("1", ""):
                used.update(ch.offset)
        return max(used) if used else 0


@dataclass
class FixtureType:
    name: str
    manufacturer: str
    short_name: str = ""
    long_name: str = ""
    fixture_type_id: str = ""
    data_version: str = ""
    attributes: dict[str, Attribute] = field(default_factory=dict)
    geometries: list[Geometry] = field(default_factory=list)  # racines
    modes: list[DMXMode] = field(default_factory=list)
    source: Optional[Path] = None
    xml_root: Optional[ET.Element] = field(default=None, repr=False)

    def all_geometries(self) -> Iterator[Geometry]:
        for root in self.geometries:
            yield from root.walk()

    def geometry(self, name: str) -> Optional[Geometry]:
        for g in self.all_geometries():
            if g.name == name:
                return g
        return None

    def top_level(self, name: str) -> Optional[Geometry]:
        for g in self.geometries:
            if g.name == name:
                return g
        return None

    def mode(self, name: str) -> Optional[DMXMode]:
        for m in self.modes:
            if m.name == name:
                return m
        return None


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def load(path: str | Path) -> FixtureType:
    """Charge un fichier .gdtf (ou un description.xml seul)."""
    path = Path(path)
    if path.suffix.lower() == ".xml":
        data = path.read_bytes()
    else:
        try:
            with zipfile.ZipFile(path) as zf:
                data = zf.read("description.xml")
        except KeyError as exc:
            raise GdtfError(f"{path.name} : pas de description.xml dans l'archive") from exc
        except zipfile.BadZipFile as exc:
            raise GdtfError(f"{path.name} : ce n'est pas une archive GDTF valide") from exc
    ft = parse_description(data)
    ft.source = path
    return ft


def parse_description(data: bytes) -> FixtureType:
    try:
        root = ET.parse(io.BytesIO(data)).getroot()
    except ET.ParseError as exc:
        raise GdtfError(f"description.xml illisible : {exc}") from exc
    if root.tag != "GDTF":
        raise GdtfError(f"racine inattendue <{root.tag}>, <GDTF> attendu")
    node = root.find("FixtureType")
    if node is None:
        raise GdtfError("pas de <FixtureType> dans description.xml")

    ft = FixtureType(
        name=node.get("Name", ""),
        manufacturer=node.get("Manufacturer", ""),
        short_name=node.get("ShortName", ""),
        long_name=node.get("LongName", ""),
        fixture_type_id=node.get("FixtureTypeID", ""),
        data_version=root.get("DataVersion", ""),
        xml_root=root,
    )

    for a in node.iterfind("AttributeDefinitions/Attributes/Attribute"):
        ft.attributes[a.get("Name", "")] = Attribute(
            name=a.get("Name", ""),
            pretty=a.get("Pretty", ""),
            feature=a.get("Feature", ""),
            activation_group=a.get("ActivationGroup", ""),
        )

    geos = node.find("Geometries")
    if geos is not None:
        ft.geometries = [_parse_geometry(child, None) for child in geos if child.tag in GEOMETRY_TAGS]

    for m in node.iterfind("DMXModes/DMXMode"):
        ft.modes.append(_parse_mode(m))

    return ft


def _parse_geometry(el: ET.Element, parent: Optional[Geometry]) -> Geometry:
    g = Geometry(
        name=el.get("Name", ""),
        kind=el.tag,
        model=el.get("Model", ""),
        position=el.get("Position", ""),
        reference=el.get("Geometry", "") if el.tag == "GeometryReference" else "",
        parent=parent,
    )
    if g.is_reference:
        for b in el.iterfind("Break"):
            g.breaks.append(Break(
                dmx_offset=_int(b.get("DMXOffset"), 1),
                dmx_break=_int(b.get("DMXBreak"), 1),
            ))
    g.children = [_parse_geometry(c, g) for c in el if c.tag in GEOMETRY_TAGS]
    return g


def _parse_mode(el: ET.Element) -> DMXMode:
    mode = DMXMode(
        name=el.get("Name", ""),
        geometry=el.get("Geometry", ""),
        description=el.get("Description", ""),
    )
    for ch in el.iterfind("DMXChannels/DMXChannel"):
        offset_raw = (ch.get("Offset") or "None").strip()
        offset = None if offset_raw in ("None", "") else [int(x) for x in offset_raw.split(",")]
        channel = DMXChannel(
            geometry=ch.get("Geometry", ""),
            offset=offset,
            dmx_break=ch.get("DMXBreak", "1"),
        )
        for lc in ch.iterfind("LogicalChannel"):
            logical = LogicalChannel(attribute=_last(lc.get("Attribute", "")))
            for cf in lc.iterfind("ChannelFunction"):
                logical.functions.append(ChannelFunction(
                    name=cf.get("Name", ""),
                    attribute=_last(cf.get("Attribute", "NoFeature")),
                    dmx_from=cf.get("DMXFrom", "0/1"),
                    default=cf.get("Default", ""),
                ))
            channel.logical_channels.append(logical)
        mode.channels.append(channel)
    for r in el.iterfind("Relations/Relation"):
        mode.relations.append(Relation(
            name=r.get("Name", ""), master=r.get("Master", ""),
            follower=r.get("Follower", ""), type=r.get("Type", ""),
        ))
    return mode


def _int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _last(node_link: str) -> str:
    """Les liens 'Node' peuvent être pointés (A.B.C) : l'attribut est le dernier maillon."""
    return node_link.split(".")[-1] if node_link else node_link
