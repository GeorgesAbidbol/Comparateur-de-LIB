# Manuel grandMA3 2.3 : fixture types et attributs (lecture du 02/11/2026)

Pages lues (help.malighting.com/grandMA3/2.3/HTML/…) : fixture_types, ft_import, ft_import_gdtf,
ft_conflicts_in_fixture_types, edit-fixture-types, ft_build, ft_insert_fixture_types,
ft_insert_geometries, ft_link_models_geometries, ft_insert_dmx, ft_export,
patch_attribute_definitions, patch_attribute_activation_group, patch_attribute_feature_group,
patch_parameter_list, keyword_attribute.

Le manuel 2.3 est un guide pas à pas (une lyre Base > Yoke > Head > Beam). Il ne détaille ni les
GeometryReference, ni les breaks, ni les canaux virtuels, ni la conversion GDTF -> MA3. Pour ces
points, nos références restent la spec GDTF et les XML exportés par la console de Jo.

## Attributs

- La console a **366 attributs prédéfinis** (la spec GDTF 1.2 en liste 280). Le maximum est de
  1024 attributs par show. On peut créer des attributs maison, mais MA conseille les attributs
  d'usine. Certains attributs GDTF n'existent pas dans la MA3 (Jo).
- **Tout attribut doit avoir une feature.** Chaque feature group reçoit automatiquement son
  **pool de presets**. Un attribut mal rangé envoie donc ses valeurs dans le mauvais pool : c'est
  le cas du « Led Control » du Nando, déclaré en Dimmer.Dimmer, qui part dans les presets Dimmer.
- Les ActivationGroups d'usine vont avec les attributs d'usine. MA déconseille de les modifier,
  car cela peut empêcher de stocker toutes les valeurs attendues. Un groupe maison doit être créé
  avant d'être utilisé.
- Le manuel ne donne **pas** la liste des 366 attributs. Jo ne peut pas l'exporter : dans la
  console, la liste dépend des fixtures patchés dans le show. La table
  `src/ma3lib/data/ma3_attributes.json` est donc construite au fil de l'eau à partir des XML MA3
  de Jo (111 attributs standard au 02/11/2026) : relancer `tools/build_attribute_tables.py` avec
  chaque nouvel export. La liste GDTF reste la base des propositions.
- Les numéros d'attribut changent d'un show à l'autre : il faut toujours se référer au **nom**.

## DMX channels

- Quand on choisit l'attribut d'un LogicalChannel, **la console renomme le canal
  `Geometry_Attribute`** (ex. Yoke_Pan, Beam_ColorRGB_R). Renommer un attribut oblige donc à
  corriger tous les liens vers ce canal : InitialFunction / DefaultChannelFunction, Relations
  Master/Follower, ModeMaster.
- L'attribut se choisit au niveau du LogicalChannel, puis de nouveau au niveau de chaque
  ChannelFunction, avec sa plage physique.
- La Parameter List affiche les colonnes Coarse, Fine et Ultra : c'est bien le nom du 3e octet
  (on avait supposé « Ultra » dans gdtf.MA3_BYTES).

## Import, export et fichiers

- Pour importer un GDTF depuis une clé, le fichier doit être dans `grandMA3/gma3_library/fixturetypes`
  et avoir l'extension .gdtf ou .GDTF.
- L'export propose « User » (format grandMA3, XML) ou « GDTF ». Sans nom saisi, le fichier
  s'appelle **`manufacturer@name.xml`** (ou .gdtf).
  - Dossier interne : `C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes` (confirmé par Jo).
  - Dossier USB d'après la page d'export : `E:\grandMA3\library\fixturetypes`. Cela **contredit** la
    page d'import GDTF et la clé de Jo (`grandMA3\gma3_library\fixturetypes`). On garde le chemin
    de Jo et on accepte `grandMA3/library` comme variante.
- **La version du fixture type ne doit pas dépasser celle de la console.** Un fixture exporté
  depuis une version plus récente peut être mal importé. On écrira donc toujours
  `DataVersion="2.3.2.0"`.
- Colonne Source : une librairie MA, « User » (GDTF Share et fixtures MA3 importés) ou Share.

## Conflits (contrôle après dépôt)

- Dans le Patch, un fixture type en **orange** est utilisable mais peut mal fonctionner. En
  **rouge**, il contient une erreur et n'apparaît plus hors du menu Patch.
- Le bouton Edit > **Show Conflicts** en donne la liste. C'est le test à faire sur l'onPC après
  chaque fichier produit par l'outil (étape 4).

## Géométries

- Grille des sous-fixtures : Grid Auto (d'après la position des géométries) ou Manual
  (Grid X/Y/Z, Swap XY, Inv X/Y/Z). On peut aussi la surcharger par fixture dans le Patch.
- Mettre à l'échelle une géométrie modifie son modèle, et donc toutes les géométries qui
  partagent ce modèle.
