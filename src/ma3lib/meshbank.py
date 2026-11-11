"""Banque de meshes de Banane Pot : des formes simples, fabriquées par l'appli (Jo, 11/11/2026 :
« il faudrait une banque de base, même si c'est des formes simples »).

Chaque forme est un petit fichier glTF binaire (.glb) calculé ici, sans dépendance. Dans le
fixture, c'est un <Model Name="…" File="bananepot_…"> ; à l'export, le fichier est intégré
comme n'importe quel mesh de GDTF. Repère GDTF : X largeur, Y profondeur, Z vers le haut ;
le glb est écrit Y vers le haut comme le veut glTF.
"""

from __future__ import annotations

import json
import math
import struct
from functools import lru_cache

PREFIX = "bananepot_"
Tri = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


def _box(c, s) -> list[Tri]:
    (cx, cy, cz), (sx, sy, sz) = c, s
    p = [(cx + dx * sx / 2, cy + dy * sy / 2, cz + dz * sz / 2)
         for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return _outward([t for a, b, c_, d in quads for t in ((p[a], p[b], p[c_]), (p[a], p[c_], p[d]))], c)


def _cylinder(c, radius, length, axis="z", n=24) -> list[Tri]:
    def pt(angle, h):
        u, v = radius * math.cos(angle), radius * math.sin(angle)
        x, y, z = {"z": (u, v, h), "y": (u, h, v), "x": (h, u, v)}[axis]
        return (c[0] + x, c[1] + y, c[2] + z)

    def mid(h):
        x, y, z = {"z": (0, 0, h), "y": (0, h, 0), "x": (h, 0, 0)}[axis]
        return (c[0] + x, c[1] + y, c[2] + z)

    tris = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        lo0, lo1, hi0, hi1 = pt(a0, -length / 2), pt(a1, -length / 2), pt(a0, length / 2), pt(a1, length / 2)
        tris += [(lo0, lo1, hi1), (lo0, hi1, hi0), (mid(-length / 2), lo1, lo0), (mid(length / 2), hi0, hi1)]
    return _outward(tris, c)


def _sphere(c, radius, rings=10, n=20) -> list[Tri]:
    def pt(i, j):
        t, a = math.pi * i / rings, 2 * math.pi * j / n
        return (c[0] + radius * math.sin(t) * math.cos(a), c[1] + radius * math.sin(t) * math.sin(a),
                c[2] + radius * math.cos(t))

    tris = []
    for i in range(rings):
        for j in range(n):
            a, b, c_, d = pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j + 1)
            if i:
                tris.append((a, b, d))
            if i < rings - 1:
                tris.append((b, c_, d))
    return _outward(tris, c)


def _outward(tris: list[Tri], center) -> list[Tri]:
    """Faces tournées vers l'extérieur de la forme (convexe autour de `center`)."""
    out = []
    for a, b, c in tris:
        n = _normal(a, b, c)
        g = [(a[k] + b[k] + c[k]) / 3 - center[k] for k in range(3)]
        out.append((a, b, c) if sum(n[k] * g[k] for k in range(3)) >= 0 else (a, c, b))
    return out


def _normal(a, b, c):
    u, v = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(x * x for x in n)) or 1.0
    return tuple(x / length for x in n)


def _yoke() -> list[Tri]:  # un U : la traverse en bas, deux bras
    return (_box((0, 0, -0.17), (0.40, 0.12, 0.06)) + _box((-0.18, 0, 0.03), (0.04, 0.12, 0.34))
            + _box((0.18, 0, 0.03), (0.04, 0.12, 0.34)))


# nom affiché -> (triangles, Length X, Width Y, Height Z en mètres)
SHAPES = {
    "Base": (lambda: _box((0, 0, 0), (0.35, 0.35, 0.10)), 0.35, 0.35, 0.10),
    "Yoke": (_yoke, 0.40, 0.12, 0.40),
    "Head": (lambda: _cylinder((0, 0, 0), 0.13, 0.36, "z"), 0.26, 0.26, 0.36),
    "Sphere": (lambda: _sphere((0, 0, 0), 0.10), 0.20, 0.20, 0.20),
    "Barre": (lambda: _box((0, 0, 0), (1.00, 0.10, 0.10)), 1.00, 0.10, 0.10),
    "Panneau": (lambda: _box((0, 0, 0), (0.50, 0.50, 0.08)), 0.50, 0.50, 0.08),
    "Pixel": (lambda: _cylinder((0, 0, 0), 0.03, 0.02, "z"), 0.06, 0.06, 0.02),
}


def names() -> list[str]:
    return list(SHAPES)


def stem(name: str) -> str:
    """Nom de fichier (sans extension) du mesh de la banque."""
    return PREFIX + name.lower()


def size(name: str) -> tuple[float, float, float]:
    return SHAPES[name][1:]


@lru_cache(maxsize=None)
def glb(name: str) -> bytes:
    """Le fichier .glb de la forme : positions + normales, faces plates, sans index."""
    tris = SHAPES[name][0]()
    pos, nor = [], []
    for a, b, c in tris:
        n = _normal(a, b, c)
        for x, y, z in (a, b, c):
            pos += [x, z, -y]  # GDTF (X, Y, Z haut) -> glTF (X, Y haut, Z vers soi)
            nor += [n[0], n[2], -n[1]]
    count = len(pos) // 3
    data = struct.pack(f"<{len(pos)}f", *pos) + struct.pack(f"<{len(nor)}f", *nor)
    half = len(data) // 2
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    doc = {
        "asset": {"version": "2.0", "generator": "Banane Pot"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "mode": 4}]}],
        "buffers": [{"byteLength": len(data)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": half, "target": 34962},
                        {"buffer": 0, "byteOffset": half, "byteLength": half, "target": 34962}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3",
                       "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
                      {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"}],
    }
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    data += b"\0" * (-len(data) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(data), 0x004E4942) + data
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def files_for(stems) -> dict[str, bytes]:
    """Fichiers de la banque demandés par un fixture, rangés comme dans une archive GDTF."""
    by_stem = {stem(n): n for n in SHAPES}
    return {f"models/gltf/{s}.glb": glb(by_stem[s]) for s in stems if s in by_stem}
