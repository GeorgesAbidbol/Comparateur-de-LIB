# Format des fixture types exportés par grandMA3 2.3.2.0

Observé sur 4 exports de Jo (31/10/2026) : JDC Line 1000, Color Strike M,
Robin Esprite. C'est ce que MA3 écrit dans `gma3_library\fixturetypes`.
Ce n'est **pas** du GDTF, mais c'est très proche (même arbre, autres noms).

## Différences avec GDTF

| | GDTF 1.2 (`description.xml` dans un zip) | MA3 (`.xml` en clair) |
|---|---|---|
| Racine | `<GDTF DataVersion="1.2">` | `<GMA3 DataVersion="2.3.2.0">` |
| Identifiant | `FixtureTypeID="AA476C50-FE73-…"` | `Guid="AA 47 6C 50 FE 73 …"` (octets séparés par des espaces) |
| Adresse d'un canal | `Offset="1,2"` | `Coarse="1" Fine="2"` (Ultra… pour 24 bits) |
| Canal virtuel | `Offset="None"` | ni `Coarse` ni `Fine` |
| Géométrie d'un canal | nom simple (`Pixel`) | **chemin complet pointé** (`Base.Body.Plate`) ; nom simple pour un modèle référencé |
| Break de référence | `<Break DMXOffset="4" DMXBreak="1"/>` | `<Break DMXPatch="4"/>` (vide = 1) |
| Valeurs DMX | `"255/1"` | hexadécimal (`FFFFFF`, `7FFF7F`) |
| Canal par défaut | `InitialFunction` | `DefaultChannelFunction="Dimmer.DIMMER"` |
| Mode | `Name`, `Geometry` | + `XYZ="No"`, `DiveInto="Yes"` |
| Images | fichiers du zip | intégrées en Base64 (`<Block Base64=…>`, `DependencyExport`) |
| Grille | — | `GridAuto`, `GridX/Y/Z` sur les géométries |

Attributs renommés par MA3 à l'import :
`ColorAdd_R/G/B/CW` → `ColorRGB_R/G/B/CW`, `ColorSub_C/M/Y` → `ColorRGB_R/G/B`.

## Ce que fait Jo quand il nettoie (référence : JDC Line 1000, mode 5)

1. **Supprime les modes inutiles** (modes 1 à 4 du JDC) et **suffixe « JO »**
   les modes retravaillés (`Mode 5 Multipix (196ch) JO`). Note `Note="JO"` sur le fixture.
2. **Range les pixels sous la géométrie qui porte leurs canaux maîtres** :
   - GDTF d'origine : `Module A` contient la référence « RGB Seg Contr A » (maître)
     et, à côté, un groupe `Single RGB A` avec les 20 pixels ;
   - version Jo : `Module A` → `RGB Segment Control Overhall A` (vraie géométrie
     Beam, porte Dimmer/Strobe/CTC) → 20 références `RGB Single A 1…20`.
   Résultat dans MA3 : Module > Segment > Pixels, le maître pilote ses enfants.
3. **Un modèle de pixel par module** (`RGB Pix Mode 5 A` et `… B`) plutôt qu'un
   modèle commun avec des breaks.
4. **Remappe des attributs** pour retrouver les données (StrobeRate → Shutter1).
5. Laisse parfois des restes (arbres des modes 6/7 sans mode associé).

**Règle validée par Jo (31/10/2026)** : le nettoyeur travaille mode par mode et
**ne supprime jamais un mode**. Les modes non retravaillés restent tels quels,
avec leurs géométries. Un nettoyage des modes eux-mêmes sera une fonction séparée,
plus tard, si besoin.

**Quand on retravaille un mode** : on réutilise les **mêmes géométries et les mêmes
modèles de référence** pour un même type d'instance / d'arborescence, d'un mode à
l'autre, au lieu de recopier un arbre par mode (le JDC d'origine a un arbre
« … Mode 5 », « … Mode 6 », « … Mode 7 » quasi identique). Le nettoyeur proposera
de rattacher un mode retravaillé aux géométries existantes compatibles.

## Conséquences pour l'outil

- Lire **les deux formats** (GDTF et XML MA3) : les sources viennent de GDTF Share,
  les librairies déjà retravaillées sont en XML MA3.
- Comparer un GDTF avec sa version MA3 doit tenir compte des renommages
  d'attributs ci-dessus.
- Format d'export : **XML MA3 direct** (choix de Jo, 31/10/2026), même format que ses exports 2.3.2.0.
