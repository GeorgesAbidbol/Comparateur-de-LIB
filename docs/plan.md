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

   Ajouts du 11/11/2026 (retours de Jo) : panneau de droite de l'atelier actif (nom, type, modèle
   de référence choisi ou créé, mesh avec banque de formes simples `meshbank.py` ou repris d'un
   autre GDTF), correction de la charte DMX par géométrie (`charte_dmx.py` : adresse, 8/16 bits,
   attribut, défaut, ajout, retrait ; GDTF seulement), section « GDTF Share » en explorateur
   (`gui/share.py`, fabricants seulement, compte dans le coffre Windows), comparateur en deux
   panneaux. Installeur Windows préparé (`packaging/`), à fabriquer quand Jo le demandera.

5. **Créer un fixture de zéro** (Jo, 11/11/2026 : « partir de 0, soit en glissant un PDF, soit en
   rentrant soi-même les paramètres, adresses et arborescence de géométrie »).
   Fait (v0.5.0) : section « Créer » de l'appli (`gui/creer.py`).
   - On glisse la notice PDF : `pdfchart.py` lit les tableaux de la charte DMX (une colonne de
     numéros par mode, nom, plages de-à, défaut ; tableau résumé + tableau détaillé rapprochés
     par leurs numéros de canal ; Fine rattaché à son canal). Vérifié sur la notice
     PROLIGHTS Muse Fresnel70CT+ (5 modes, 35 à 46 canaux). Seuls les tableaux tracés sont lus.
   - Ou on saisit tout à la main : modes, canaux, Fine, attribut (proposé d'après le nom,
     `creation.deviner`), géométrie, copies, défaut, plages nommées.
   - « Copies » : une géométrie nommée répétée N fois devient un modèle + N références aux
     adresses contiguës ; avec plusieurs modes, une base par mode (règles de Jo).
   - « Créer le fixture » fabrique un vrai GDTF en mémoire (`creation.construire`) et l'ouvre dans
     l'atelier : arbre de géométries, puis export XML MA3 comme pour n'importe quel fixture.
   - Le projet en cours s'enregistre en `.bpot.json` pour être repris.
   - « Tout récupérer » (Jo, 11/11/2026, après l'import du Muse dans onPC) : émetteurs LED et filtres
     CMY reliés aux canaux, espace couleur, valeurs physiques (pan/tilt/zoom d'après le texte de la
     notice, degrés / kelvins / % lus dans les plages), canal découpé en fonctions (Shutter1Strobe,
     Color1WheelSpin, IrisPulseClose…), roues de couleurs et de gobos avec emplacements reliés aux
     plages, lectures multiples d'un canal (ModeMaster : indexation ou rotation selon un autre
     canal), tableaux annexes (« Control Channel », « Virtual colors ») rattachés à leur canal.
     Les couleurs des émetteurs et des emplacements sont des valeurs TYPIQUES (`creation.EMETTEURS`,
     `creation.COULEURS`) : les notices ne donnent pas de mesures.
   Images des roues (`pdfimages.py`) : sur les pages « gobo / colour wheel », les images sont
   rattachées aux emplacements par le texte voisin, sinon dans l'ordre ; elles vivent dans le projet
   (`Projet.images`), l'archive GDTF (`wheels/`) et l'export MA3 (contenu intégré dans `GoboImage`,
   vérifié dans onPC par Jo le 13/11/2026 ; les exports de la console ne portent que la référence au pool).
   Dans « Créer » : boutons « Image… », « Inverser », « Retirer l'image » sur une plage de roue.
   Reste : notices sans tableau tracé (texte seul), gobos dessinés en traits (vectoriels),
   fréquences de strobe quand la notice ne les donne pas, gélatines par catégorie (Muse : 11 tableaux), poids / puissance,
   test d'import onPC.

## Points à vérifier sur le matériel de Jo

- [x] Grille MA3 : placée à la main = `GridAuto="Manual"` + `GridX/GridY/GridZ`, relatifs aux
  sœurs (Color Strike M 47ch JO, JDC JO). La proposition de l'atelier retrouve 24/25 et 41/45
  des placements manuels de Jo.

- [x] Clé USB : `<lecteur>:\grandMA3\gma3_library\fixturetypes` (confirmé par Jo).
- [x] onPC : `C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes` (confirmé par Jo).
- [ ] Import onPC d'un XML converti par l'outil : Nando 502 OK (Jo, 10/11/2026), iTetra2 à confirmer.
  Maillages 3D, vignette, gobos visibles ? (gobos : référence au pool seulement, comme la console.)
- [ ] Import onPC d'un fixture créé de zéro (Muse Fresnel70CT+ : attributs proposés, plages).
- [ ] Connexion GDTF Share réelle (non testable depuis l'environnement de dev).
- [ ] Comment MA3 2.3.2.0 affiche un dimmer virtuel ajouté dans un GDTF.
- [x] Axis : une tête seule se fond dans l'instance principale (iTetra2) ; plusieurs têtes
  (12 tilts, copiées ou en références) = autant d'instances (confirmé par Jo, 10/11/2026).
- [x] iTetra2 : un mode choisit le Break d'une référence par ses canaux (`DMXBreak="1"` →
  premier Break, `"Overwrite"` → dernier). Voir `docs/gdtf-notes.md`.
