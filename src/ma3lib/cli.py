"""Ligne de commande de l'étape 1 (l'interface graphique viendra à l'étape 2).

    python -m ma3lib info  <fichier.gdtf>         contenu : modes, canaux, géométries
    python -m ma3lib check <fichier.gdtf> [...]   diagnostic géométries / dimmer
    python -m ma3lib subfix <fichier> [mode]       sous-fixtures comme le SubfixtureOverview MA3
    python -m ma3lib charte <fichier> <charte.csv>  comparaison avec la charte DMX constructeur
    python -m ma3lib targets                      destinations MA3 détectées
    python -m ma3lib share-search <mots>          recherche sur GDTF Share
    python -m ma3lib share-get <rid> [dossier]    téléchargement depuis GDTF Share
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import charte, diagnostic, gdtf, ma3_paths, subfixtures

LEVEL_MARK = {diagnostic.ERREUR: "XX", diagnostic.ALERTE: "!!", diagnostic.INFO: "--"}


def print_tree(g: gdtf.Geometry, index: int = 1, indent: str = "  ") -> None:
    """Affiche l'arbre comme l'éditeur de MA3 : « n° (nb d'enfants) » puis le nom.
    Une référence compte 1 enfant (le modèle qu'elle instancie)."""
    extra = f" -> {g.reference}" if g.is_reference else ""
    if g.breaks:
        extra += " (" + ", ".join(f"break {b.dmx_break} @ {b.dmx_offset}" for b in g.breaks) + ")"
    kids = 1 if g.is_reference else len(g.children)
    num = f"{index} ({kids})" if kids else f"{index}"
    print(f"{indent}{num:<9}{g.name} [{g.kind}]{extra}")
    for i, child in enumerate(g.children, 1):
        print_tree(child, i, indent + "  ")


def cmd_info(args) -> int:
    ft = gdtf.load(args.file)
    print(f"{ft.manufacturer} - {ft.name}  (GDTF {ft.data_version})")
    print(f"{len(ft.attributes)} attributs définis, {sum(1 for _ in ft.all_geometries())} géométries")
    print("\nGéométries :")
    for i, root in enumerate(ft.geometries, 1):
        print_tree(root, i)
    for mode in ft.modes:
        print(f"\nMode « {mode.name} » : {len(mode.channels)} canaux, empreinte {mode.footprint}")
        for ch in mode.channels:
            addr = "virtuel" if ch.is_virtual else ",".join(map(str, ch.offset))
            brk = f" brk {ch.dmx_break}" if ch.dmx_break not in ("1", "") else ""
            subs = ", ".join(lc.attribute for lc in ch.logical_channels[1:])
            print(f"  {addr:>8}{brk}  {ch.name}" + (f"  (+ {subs})" if subs else ""))
    return 0


def cmd_check(args) -> int:
    worst = 0
    for f in args.files:
        ft = gdtf.load(f)
        print(f"== {Path(f).name} : {ft.manufacturer} - {ft.name}")
        findings = diagnostic.diagnose(ft)
        if not findings:
            print("  rien à signaler")
        for fd in findings:
            print(f"  {LEVEL_MARK[fd.level]} {fd.message}")
            for d in fd.details[:12]:
                print(f"       {d}")
            if len(fd.details) > 12:
                print(f"       … {len(fd.details) - 12} de plus")
            if fd.level == diagnostic.ERREUR:
                worst = 1
    return worst


def cmd_subfix(args) -> int:
    ft = gdtf.load(args.file)
    modes = [m for m in ft.modes if not args.mode or args.mode.lower() in m.name.lower()]
    for mode in modes:
        print(f"== Mode « {mode.name} »")
        tree = subfixtures.overview(ft, mode)
        if tree is None:
            print("  géométrie racine introuvable")
            continue
        print("\n".join("  " + line for line in subfixtures.lines(tree, max_children=args.max)))
    return 0


def cmd_charte(args) -> int:
    ft = gdtf.load(args.file)
    rows = charte.load_chart(args.chart)
    chart_modes = sorted({r.mode for r in rows})
    total_issues = 0
    for cm in chart_modes:
        if args.mode and args.mode.lower() not in cm.lower():
            continue
        mode = next((m for m in ft.modes if m.name.lower().startswith(cm.lower())), None) \
            or next((m for m in ft.modes if cm.lower() in m.name.lower()), None)
        if mode is None:
            print(f"== {cm} : aucun mode correspondant dans le fixture")
            continue
        matches = charte.compare(ft, mode, [r for r in rows if r.mode == cm])
        issues = [m for m in matches if m.status not in (charte.OK, charte.IGNORE)]
        ignored = [m for m in matches if m.status == charte.IGNORE]
        total_issues += len(issues)
        ok = len(matches) - len(issues) - len(ignored)
        extra = f", {len(ignored)} inutilisé(s) selon la notice" if ignored else ""
        print(f"== {cm} (notice) <-> « {mode.name} » : {ok} canaux conformes, {len(issues)} écart(s){extra}")
        for m in issues:
            fn = m.chart.function if m.chart else "-"
            got = f"{m.channel.instance} : {', '.join(m.channel.attributes)}" if m.channel else "-"
            print(f"  [{m.status}] ch {m.address:>3}  notice « {fn} »  |  fixture {got}")
            if m.note:
                print(f"           {m.note}")
            if m.suggestion:
                print(f"           -> proposition : {m.suggestion}")
    return 1 if total_issues else 0


def cmd_targets(args) -> int:
    targets = ma3_paths.find_targets()
    if not targets:
        print("Aucune destination MA3 trouvée (clé USB préparée par la console, ou onPC installé).")
        return 1
    for t in targets:
        print(f"{t.label}\n   -> {t.fixture_dir}")
    return 0


def cmd_share_search(args) -> int:
    from .gdtf_share import GdtfShareClient, search
    for e in search(GdtfShareClient().list(), " ".join(args.words))[:50]:
        print(f"{e.rid:>7}  {e.manufacturer} - {e.fixture}  [{e.revision}]  {len(e.modes)} mode(s)")
    return 0


def cmd_share_get(args) -> int:
    from .gdtf_share import GdtfShareClient
    client = GdtfShareClient()
    entry = next((e for e in client.list() if e.rid == args.rid), None)
    if entry is None:
        print(f"rid {args.rid} introuvable sur GDTF Share")
        return 1
    print(client.download(entry, Path(args.dest)))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ma3lib", description="Comparateur de LIB grandMA3 (GDTF)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info"); s.add_argument("file"); s.set_defaults(func=cmd_info)
    s = sub.add_parser("check"); s.add_argument("files", nargs="+"); s.set_defaults(func=cmd_check)
    s = sub.add_parser("subfix"); s.add_argument("file"); s.add_argument("mode", nargs="?", default="")
    s.add_argument("--max", type=int, default=3, help="enfants affichés par niveau (0 = tous)")
    s.set_defaults(func=cmd_subfix)
    s = sub.add_parser("charte"); s.add_argument("file"); s.add_argument("chart")
    s.add_argument("mode", nargs="?", default=""); s.set_defaults(func=cmd_charte)
    s = sub.add_parser("targets"); s.set_defaults(func=cmd_targets)
    s = sub.add_parser("share-search"); s.add_argument("words", nargs="+"); s.set_defaults(func=cmd_share_search)
    s = sub.add_parser("share-get"); s.add_argument("rid", type=int); s.add_argument("dest", nargs="?", default="gdtf")
    s.set_defaults(func=cmd_share_get)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except gdtf.GdtfError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
