"""Construit les tables d'attributs de référence (src/ma3lib/data/*.json).

    python tools/build_attribute_tables.py gdtf-spec.md [fixture_ma3.xml ...]

- gdtf_attributes.json : annexe B de la spec GDTF 1.2
  (https://github.com/mvrdevelopment/spec/blob/main/gdtf-spec.md)
- ma3_attributes.json  : attributs réellement présents dans des fixture types exportés par
  grandMA3 2.3.2.0 (liste partielle tant qu'on n'a pas l'export complet de la console).
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "ma3lib" / "data"


def gdtf_table(spec: Path) -> dict:
    text = spec.read_text(encoding="utf-8")
    annex = text[text.index("## Annex B"):text.index("## Annex C")]
    out = {}
    for m in re.finditer(r"<Attribute\s+([^>]*?)/?>", annex):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        out[attrs["Name"]] = {"feature": attrs.get("Feature", ""),
                              "activation_group": attrs.get("ActivationGroup", ""),
                              "main": attrs.get("MainAttribute", ""),
                              "pretty": attrs.get("Pretty", ""),
                              "physical_unit": attrs.get("PhysicalUnit", "")}
    return out


def ma3_table(files: list[Path], gdtf: dict) -> dict:
    """On ne garde que les attributs standard (motif GDTF, après renommage MA3 ColorRGB_ -> ColorAdd_)
    ou marqués Special par la MA3 : les attributs maison des fabricants ne prouvent rien."""
    pats = [re.compile("^" + re.escape(k).replace(r"\(n\)", r"\d+").replace(r"\(m\)", r"\d+") + "$", re.I)
            for k in gdtf]
    out = {}
    for f in files:
        root = ET.parse(f).getroot()
        for a in root.iter("Attribute"):
            name = a.get("Name", "")
            if not a.get("Special") and not any(p.match(name.replace("ColorRGB_", "ColorAdd_")) for p in pats):
                continue
            out.setdefault(a.get("Name"), {"feature": a.get("Feature", ""),
                                           "activation_group": a.get("ActivationGroup", ""),
                                           "main": a.get("MainAttribute", ""),
                                           "pretty": a.get("Pretty", ""),
                                           "physical_unit": a.get("PhysicalUnit", ""),
                                           "special": a.get("Special", "")})
    return dict(sorted(out.items()))


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    g = gdtf_table(Path(sys.argv[1]))
    (DATA / "gdtf_attributes.json").write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"GDTF : {len(g)} attributs")
    if len(sys.argv) > 2:
        m = ma3_table([Path(p) for p in sys.argv[2:]], g)
        (DATA / "ma3_attributes.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"MA3 : {len(m)} attributs")
