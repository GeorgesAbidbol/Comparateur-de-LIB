"""Ligne de commande de l'étape 1 (l'interface graphique viendra à l'étape 2).

    python -m ma3lib info  <fichier.gdtf>         contenu : modes, canaux, géométries
    python -m ma3lib check <fichier.gdtf> [...]   diagnostic géométries / dimmer
    python -m ma3lib subfix <fichier> [mode]       sous-fixtures comme le SubfixtureOverview MA3
    python -m ma3lib charte <fichier> <charte.csv>  comparaison avec la charte DMX constructeur
    python -m ma3lib attributs <fichier>           attributs mal rangés (feature, groupe, maison)
    python -m ma3lib remap <fichier> [règles]       renomme / range les attributs, écrit une copie
    python -m ma3lib targets                      destinations MA3 détectées
    python -m ma3lib share-search <mots>          recherche sur GDTF Share
    python -m ma3lib share-get <rid> [dossier]    téléchargement depuis GDTF Share
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import attributs, charte, diagnostic, gdtf, ma3_paths, remap, subfixtures

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
        modes = [m for m in ft.modes if cm.lower() in m.name.lower()]
        if not modes:
            print(f"== {cm} : aucun mode correspondant dans le fixture")
            continue
        for mode in modes:
            total_issues += _print_chart_mode(ft, mode, cm, [r for r in rows if r.mode == cm])
    return 1 if total_issues else 0


def _print_chart_mode(ft, mode, cm, rows) -> int:
    matches = charte.compare(ft, mode, rows)
    issues = [m for m in matches if m.status not in (charte.OK, charte.IGNORE)]
    ignored = [m for m in matches if m.status == charte.IGNORE]
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
    return len(issues)


def cmd_attributs(args) -> int:
    ft = gdtf.load(args.file)
    issues = attributs.check(ft)
    bad = [i for i in issues if i.level == "alerte"]
    print(f"== {ft.manufacturer} - {ft.name} : {len(bad)} attribut(s) mal rangé(s)")
    for i in sorted(issues, key=lambda i: i.level != "alerte"):
        if i.level == "info" and not args.tout:
            continue
        mark = "!!" if i.level == "alerte" else "--"
        print(f"  {mark} {i.attribute} [{i.feature or '?'}{' / ' + i.activation_group if i.activation_group else ''}]"
              f" : {i.problem}")
        if i.suggestion:
            print(f"       -> proposition : {i.suggestion}")
        if i.equivalents:
            eq = ", ".join(f"{e} ({(attributs.ma3_known(e) or attributs.gdtf_standard(e) or {}).get('feature', '?')})"
                           for e in i.equivalents)
            print(f"       équivalents MA3 possibles : {eq}")
    if not args.tout:
        n = len(issues) - len(bad)
        if n:
            print(f"  ({n} info(s) masquée(s) : attributs maison et leurs équivalents MA3, conversions ; --tout pour voir)")
    return 1 if bad else 0


def _pairs(values: list[str], what: str) -> list[tuple[str, str]]:
    out = []
    for v in values or []:
        if "=" not in v:
            raise remap.RemapError(f"{what} attend « attribut=valeur », reçu « {v} »")
        a, b = v.split("=", 1)
        out.append((a.strip(), b.strip()))
    return out


def cmd_remap(args) -> int:
    ft = gdtf.load(args.file)
    rules: list[remap.Rule] = []
    try:
        if args.auto:
            rules += remap.rules_from_issues(attributs.check(ft))
        if args.regles:
            rules += remap.load_rules(args.regles)
        rules += [remap.Rule(a, rename=b) for a, b in _pairs(args.renommer, "--renommer")]
        rules += [remap.Rule(a, feature=b) for a, b in _pairs(args.feature, "--feature")]
        rules += [remap.Rule(a, activation_group="" if b in ("", "-") else b)
                  for a, b in _pairs(args.groupe, "--groupe")]
        if not rules:
            print("Aucune règle : --auto, --regles fichier.csv, --renommer, --feature ou --groupe")
            return 1
        for r in rules:
            print(f"  règle  {r.describe()}")
        for line in remap.apply(ft, rules):
            print(f"  fait   {line}")
        src = Path(args.file)
        out = Path(args.sortie) if args.sortie else src.with_name(f"{src.stem}_remap{src.suffix}")
        print(f"Écrit : {remap.save(ft, out)}")
    except remap.RemapError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_targets(args) -> int:
    targets = ma3_paths.find_targets()
    if not targets:
        print("Aucune destination MA3 trouvée (clé USB préparée par la console, ou onPC installé).")
        return 1
    for t in targets:
        print(f"{t.label}\n   -> {t.fixture_dir}")
    return 0


def cmd_export(args) -> int:
    from . import ma3xml
    ft = gdtf.load(args.file)
    if args.dossier:
        folder = Path(args.dossier)
    else:
        kind = "usb" if args.cle else "onpc" if args.onpc else ""
        targets = [t for t in ma3_paths.find_targets() if not kind or t.kind == kind]
        if not targets:
            print("Aucune destination MA3 trouvée : précise un dossier (--dossier).")
            return 1
        folder = targets[0].fixture_dir
    try:
        out = ma3xml.export(ft, folder, name=args.nom or None,
                            guid=ma3xml.new_guid() if args.nouveau_guid else None,
                            note=args.note, overwrite=args.remplacer)
    except FileExistsError as exc:
        print(f"{exc} existe déjà (--remplacer pour l'écraser)")
        return 1
    print(f"Écrit : {out}")
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
    p = argparse.ArgumentParser(prog="ma3lib", description="Banane Pot : librairies grandMA3 (GDTF, XML MA3)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info"); s.add_argument("file"); s.set_defaults(func=cmd_info)
    s = sub.add_parser("check"); s.add_argument("files", nargs="+"); s.set_defaults(func=cmd_check)
    s = sub.add_parser("subfix"); s.add_argument("file"); s.add_argument("mode", nargs="?", default="")
    s.add_argument("--max", type=int, default=3, help="enfants affichés par niveau (0 = tous)")
    s.set_defaults(func=cmd_subfix)
    s = sub.add_parser("charte"); s.add_argument("file"); s.add_argument("chart")
    s.add_argument("mode", nargs="?", default=""); s.set_defaults(func=cmd_charte)
    s = sub.add_parser("attributs"); s.add_argument("file")
    s.add_argument("--tout", action="store_true", help="afficher aussi les infos")
    s.set_defaults(func=cmd_attributs)
    s = sub.add_parser("remap"); s.add_argument("file"); s.add_argument("regles", nargs="?", default="")
    s.add_argument("-o", "--sortie", default="", help="fichier écrit (défaut : <nom>_remap.<ext>)")
    s.add_argument("--auto", action="store_true", help="appliquer les propositions du détecteur")
    s.add_argument("--renommer", action="append", metavar="ATTR=NOUVEAU")
    s.add_argument("--feature", action="append", metavar="ATTR=Groupe.Feature")
    s.add_argument("--groupe", action="append", metavar="ATTR=ActivationGroup", help="ATTR=- pour retirer")
    s.set_defaults(func=cmd_remap)
    s = sub.add_parser("targets"); s.set_defaults(func=cmd_targets)
    s = sub.add_parser("export", help="écrire le fixture en XML MA3 2.3.2.0")
    s.add_argument("file")
    s.add_argument("--dossier", default="", help="dossier de destination (défaut : onPC ou clé trouvée)")
    s.add_argument("--onpc", action="store_true"); s.add_argument("--cle", action="store_true")
    s.add_argument("--nom", default=""); s.add_argument("--note", default=None)
    s.add_argument("--nouveau-guid", action="store_true"); s.add_argument("--remplacer", action="store_true")
    s.set_defaults(func=cmd_export)
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
