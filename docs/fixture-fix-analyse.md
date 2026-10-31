# Fixture Fix : analyse fonctionnelle (à partir des captures de Jo)

Sert de modèle pour l'étape 2. Analyse faite uniquement à partir de captures
d'écran de l'utilisation du logiciel.

## Écran principal : comparaison (`reference/fixturefix-comparaison.png`)

Exemple : Ayrton Mistral, mode « Extended jo » (source) → Martin Mac Viper Profile,
mode « 16 bit Extended » (cible).

- **Barre d'outils** : New project, Open, Save, Save as, **Export all**.
  Interrupteur **Instances view** en haut à droite.
- **Onglets** : un onglet par fixture source préparé (« Mistral »), renommable,
  bouton + pour en ajouter. Un projet = plusieurs onglets.
- **Deux colonnes** : source à gauche, cible à droite. En-tête :
  `Fabricant - Fixture` + `Mode: …`.
- **Sections par instance** : « Instance 1 - Module 1 : Main Module », repliables.
  Pour MA3/GDTF, une instance correspond à une géométrie (ou une géométrie référence).
- **Une ligne par attribut** : pastille numérotée (ordre du canal), nom court
  (Pan, Dim, C1, G1<>), puis `FEATURE - ATTRIBUT` en petit (POSITION - PAN,
  COLOR - COLORRGB1), et à droite les canaux `Coarse: n | Fine: n`.
- **Code couleur des pastilles** :
  - vert : l'attribut existe des deux côtés ;
  - orange côté source : absent de la cible, les données seront perdues
    (Position MSpeed, LEDEngineEffects…, FocusMode) ;
  - orange côté cible : présent seulement dans la cible ; certains ont une
    icône ↻ (« remplacer par… ») pour y brancher un attribut source.
- **Côté source** : case à cocher par ligne et « tout cocher » par instance
  (sélection des attributs à traiter).
- **Icônes d'en-tête** : source = tout cocher, trier, supprimer ;
  cible = trier, exporter (→), supprimer.

## Remplacement d'un attribut cible (`reference/fixturefix-remplacement.png`)

- Le bouton ↻ n'apparaît que sur les lignes **orange de la cible** (attribut que
  la source n'a pas : G2<>, G3, Rate…).
- Il ouvre une liste **« Available attributes »** : uniquement les attributs de la
  source qui n'ont pas de correspondance (les orange de gauche : Position MSpeed,
  LEDEngineEffects, LEDEngineEffectRate, LEDEngineEffectStepTime, FocusMode,
  AnimationWheel, Macros/PWMFrequency…). Chaque bouton affiche nom court + ATTRIBUT.
- Choisir un attribut renomme le canal cible avec l'attribut source : les données
  du show sur cet attribut sont conservées (ligne jaune).
- Règle déduite : un attribut source ne peut être utilisé qu'une fois, et une fois
  branché il disparaît de la liste.

## Export (`reference/fixturefix-export.png`)

« Export all » ouvre « Export location » avec des boutons :
- **Downloads** ;
- **un bouton par version MA2 installée détectée** (`gma2_V_3.9.60\library`,
  `gma2_V_3.9.61\library`) ;
- **Custom location** (dernier dossier personnalisé mémorisé) ;
- **Choose directory…**

Pour nous : un bouton par dossier onPC MA3 détecté, **un bouton par clé USB MA3
branchée** (`grandMA3_library`), Téléchargements, dossier mémorisé, parcourir.

## Réglages (`reference/fixturefix-reglages.png`)

- **Startup** : recharger le dernier projet au démarrage (activé chez Jo).
- **Custom export folder** : chemin + « Select Folder » (chez Jo : `D:\Desktop`).
- **Naming** : 4 choix indépendants pour nommer le fixture exporté.
  - Nom fabricant / nom court fabricant : fabricant de la cible, « Fixture Fix »
    (choix de Jo), nom du projet, ou personnalisé.
  - Nom fixture / nom court fixture : combinaisons de nom d'onglet, nom cible,
    nom source, nom de projet et mode (`TabName To TargetName`,
    `Target Name From Source Name` (choix de Jo), `ProjectName@TargetName`,
    `TargetName_Mode`…).
- **After export** : ouvrir le dossier après export (activé chez Jo).

Pour nous (GDTF) : ces choix alimentent `Manufacturer`, `ShortName`, `Name`,
`LongName` de `<FixtureType>` et le nom du fichier `Fabricant@Fixture@Commentaire.gdtf`.
Il faudra aussi un **nouveau `FixtureTypeID` (GUID)** pour que MA3 ne confonde pas
le fixture modifié avec l'original. Valeurs par défaut reprises de celles de Jo.

## Traduction pour MA3 / GDTF

| Fixture Fix (MA2) | Comparateur de LIB (MA3) |
|---|---|
| Module / instance | Géométrie (instance de géométrie référence) |
| FEATURE - ATTRIBUT | `Attribute.Feature` + `Attribute.Name` du GDTF |
| Coarse / Fine | `DMXChannel.Offset` (1 à 4 octets) |
| Attribut virtuel (bleu) | canal `Offset="None"` |
| Remplacer (jaune) | renommer l'attribut du canal cible |

## Captures encore utiles

- [x] Le dialogue de remplacement (↻).
- [ ] Le rendu jaune après remplacement.
- [ ] L'ajout d'un attribut virtuel (bleu).
- [x] Le choix de destination d'export.
- [ ] La vue avec « Instances view » désactivé.
