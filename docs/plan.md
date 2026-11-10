# Plan

Proposé le 31/10/2026 (modifiable). Appli de bureau, usage personnel, grandMA3 2.3.2.0.

1. **Fondations GDTF** : lecture des GDTF (modes, attributs, géométries),
   diagnostic des géométries, client GDTF Share, détection des dossiers MA3.
2. **Comparateur façon Fixture Fix** : source vs cible, code couleur
   (vert correspond, orange perdu, bleu ajouté en virtuel, jaune remplacé),
   mapping manuel des attributs. Interface graphique.
   Choix avec Jo (04/11/2026) : vraie appli Windows en Qt (PySide6), menus légers ;
   arbre de connexion où l'on tire des lignes entre instances source et cible (le nombre de
   pixels diffère souvent), puis même principe pour les attributs d'une liaison ;
   rendu des étages inspiré du SubfixtureOverview / Fixture Hero de MA3
   (`reference/ma3-fixturetypes-itetra2.png`, `reference/ma3-fixturehero-jdc.png`).
   Fait : l'affichage (`ma3lib-gui`). À faire : remplacement (jaune), virtuel (bleu),
   répartir, projet sauvegardé, écriture.
3. **Atelier géométries** : arbre éditable, nettoyeur multi-instances
   (géométries copiées → 1 modèle + géométries références avec Breaks),
   ajout d'un dimmer virtuel (canal `Offset="None"` + relations `Multiply`,
   cf. spec GDTF, listing 1).
4. **Export et dépôt** : écriture du fixture corrigé en **XML MA3 2.3.2.0** (choix de Jo), copie sur clé USB MA3
   ou dans le dossier onPC, test d'import dans grandMA3 onPC.
   Fait (10/11/2026) : convertisseur GDTF → XML MA3 (`ma3lib/ma3xml.py`, règles dans
   `docs/ma3-xml-notes.md`), bouton « Exporter… » de l'atelier (nom, note, GUID, destination),
   commande `python -m ma3lib export`. Reste : export depuis le comparateur, test onPC.

5. **Créer un fixture de zéro** (idée de Jo, 10/11/2026) : à partir des données constructeur
   et de la charte DMX PDF. Claude transcrit le PDF en charte CSV (`chartes/`), l'outil
   construit modes / canaux / attributs MA3 puis demande la structure (têtes, pixels,
   sections → modèles + références), finition dans l'atelier, export XML MA3.

## Points à vérifier sur le matériel de Jo

- [x] Grille MA3 : placée à la main = `GridAuto="Manual"` + `GridX/GridY/GridZ`, relatifs aux
  sœurs (Color Strike M 47ch JO, JDC JO). La proposition de l'atelier retrouve 24/25 et 41/45
  des placements manuels de Jo.

- [x] Clé USB : `<lecteur>:\grandMA3\gma3_library\fixturetypes` (confirmé par Jo).
- [x] onPC : `C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes` (confirmé par Jo).
- [ ] Import onPC d'un XML converti par l'outil (iTetra2, Nando 502) : pas de conflit dans le Patch ?
  Maillages 3D, vignette, gobos visibles ? (gobos : référence au pool seulement, comme la console.)
- [ ] Connexion GDTF Share réelle (non testable depuis l'environnement de dev).
- [ ] Comment MA3 2.3.2.0 affiche un dimmer virtuel ajouté dans un GDTF.
- [x] Axis : une tête seule se fond dans l'instance principale (iTetra2) ; plusieurs têtes
  (12 tilts, copiées ou en références) = autant d'instances (confirmé par Jo, 10/11/2026).
- [x] iTetra2 : un mode choisit le Break d'une référence par ses canaux (`DMXBreak="1"` →
  premier Break, `"Overwrite"` → dernier). Voir `docs/gdtf-notes.md`.
