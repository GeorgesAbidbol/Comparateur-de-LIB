"""Où déposer les librairies pour grandMA3 (clé USB et onPC).

Confirmé par Jo (31/10/2026, clé préparée par sa console 2.3.2.0) :
  - clé USB : <racine>\\grandMA3\\gma3_library\\fixturetypes   (ex. E:\\grandMA3\\gma3_library\\fixturetypes)
  - onPC    : ...\\MALightingTechnology\\gma3_library\\fixturetypes  (à confirmer)
On accepte aussi <racine>\\grandMA3_library, cité dans le README de ma3-TC-Sniffer.
"""

from __future__ import annotations

import os
import shutil
import string
import sys
from dataclasses import dataclass
from pathlib import Path

# --- Réglages ------------------------------------------------------------
USB_LIBRARY_DIRS = ("grandMA3/gma3_library", "grandMA3_library")  # le premier est confirmé
ONPC_LIBRARY_DIR = "gma3_library"
FIXTURE_SUBDIR = "fixturetypes"
# -------------------------------------------------------------------------


@dataclass
class Target:
    label: str
    library_root: Path
    kind: str  # "usb" ou "onpc"

    @property
    def fixture_dir(self) -> Path:
        return self.library_root / FIXTURE_SUBDIR


def onpc_candidates() -> list[Path]:
    """Dossiers possibles de la librairie onPC selon le système."""
    paths = []
    if sys.platform.startswith("win"):
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")
        paths.append(Path(program_data) / "MALightingTechnology" / ONPC_LIBRARY_DIR)
    elif sys.platform == "darwin":
        paths.append(Path("/Library/Application Support/MALightingTechnology") / ONPC_LIBRARY_DIR)
        paths.append(Path.home() / "MALightingTechnology" / ONPC_LIBRARY_DIR)
    else:
        paths.append(Path.home() / "MALightingTechnology" / ONPC_LIBRARY_DIR)
    return paths


def removable_roots() -> list[Path]:
    """Racines de volumes susceptibles d'être une clé USB."""
    if sys.platform.startswith("win"):
        roots = []
        for letter in string.ascii_uppercase[3:]:  # à partir de D:
            root = Path(f"{letter}:\\")
            if root.exists():
                roots.append(root)
        return roots
    if sys.platform == "darwin":
        patterns = [(Path("/Volumes"), 1)]
    else:  # Linux : /media/<user>/<vol>, /run/media/<user>/<vol>, /mnt/<vol>
        patterns = [(Path("/media"), 1), (Path("/media"), 2), (Path("/run/media"), 2), (Path("/mnt"), 1)]
    roots: list[Path] = []
    for base, depth in patterns:
        if base.is_dir():
            roots += [p for p in base.glob("/".join(["*"] * depth)) if p.is_dir()]
    return roots


def find_targets(extra_roots: list[Path] | None = None) -> list[Target]:
    """Liste les destinations MA3 trouvées (clés USB déjà préparées par la console, onPC)."""
    targets: list[Target] = []
    for path in onpc_candidates():
        if path.is_dir():
            targets.append(Target(f"onPC ({path})", path, "onpc"))
    for root in [*removable_roots(), *(extra_roots or [])]:
        for sub in USB_LIBRARY_DIRS:
            lib = root / sub
            if lib.is_dir():
                targets.append(Target(f"Clé USB ({root})", lib, "usb"))
                break
    return targets


def deploy(gdtf_file: Path, target: Target, overwrite: bool = False) -> Path:
    """Copie un .gdtf dans le dossier fixture types de la destination."""
    dest_dir = target.fixture_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / gdtf_file.name
    if dest.exists() and not overwrite:
        raise FileExistsError(f"{dest} existe déjà")
    shutil.copy2(gdtf_file, dest)
    return dest
