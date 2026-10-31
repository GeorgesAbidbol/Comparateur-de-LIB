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

## Traduction pour MA3 / GDTF

| Fixture Fix (MA2) | Comparateur de LIB (MA3) |
|---|---|
| Module / instance | Géométrie (instance de géométrie référence) |
| FEATURE - ATTRIBUT | `Attribute.Feature` + `Attribute.Name` du GDTF |
| Coarse / Fine | `DMXChannel.Offset` (1 à 4 octets) |
| Attribut virtuel (bleu) | canal `Offset="None"` |
| Remplacer (jaune) | renommer l'attribut du canal cible |

## Captures encore utiles

- [ ] Le dialogue de remplacement (↻) et le rendu jaune.
- [ ] L'ajout d'un attribut virtuel (bleu).
- [ ] Le dialogue d'export (noms fabricant/fixture, destination).
- [ ] La vue avec « Instances view » désactivé.
