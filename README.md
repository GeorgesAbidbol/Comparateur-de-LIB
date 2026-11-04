# Comparateur de LIB

Outil de bureau (Windows) pour **comparer, nettoyer et préparer les librairies
GDTF de grandMA3**, sur le modèle de Fixture Fix (qui ne gère que grandMA2).

Objectifs (voir [docs/plan.md](docs/plan.md)) :

- télécharger les GDTF depuis GDTF Share ;
- comparer deux fixture types attribut par attribut (correspond / perdu / ajouté / remplacé)
  pour ne rien perdre quand on change de librairie dans un show ;
- ranger et nettoyer les géométries, en particulier les multi-instances
  qui n'utilisent pas les géométries références ;
- ajouter un dimmer virtuel ;
- déposer la librairie finale sur la clé USB MA3 ou dans le dossier onPC.

Version cible : **grandMA3 2.3.2.0**.

## État : étape 1 (fondations)

Une ligne de commande, et le début de l'interface graphique (étape 2, voir plus bas).

```
pip install -e .
ma3lib info  "Fabricant@Projo.gdtf"     # modes, canaux, arbre des géométries
ma3lib check *.gdtf                     # diagnostic géométries / références / dimmer
ma3lib subfix fixture.xml "JO"          # sous-fixtures comme le SubfixtureOverview MA3
ma3lib charte fixture.gdtf chartes/Ayrton_Nando_502.csv   # comparaison avec la notice DMX
ma3lib attributs fixture.gdtf           # attributs mal rangés (feature = pool de presets MA3)
ma3lib remap fixture.gdtf --auto        # applique les propositions, écrit fixture_remap.gdtf
ma3lib remap fixture.xml regles.csv --renommer "Led Control=LEDZoneMode" --groupe "x=-"
ma3lib targets                          # clés USB MA3 et dossier onPC détectés
ma3lib share-search robe spiider        # recherche GDTF Share (compte requis)
ma3lib share-get 12345 gdtf/            # téléchargement
```

GDTF Share : mettre ses identifiants dans les variables d'environnement
`GDTF_SHARE_USER` et `GDTF_SHARE_PASSWORD`. Rien n'est enregistré sur disque.

### Ce que détecte `check`

| Repère | Signification |
|---|---|
| `XX` | erreur de structure : nom de géométrie en double, référence cassée ou vers une géométrie non racine, canal lié à une géométrie inexistante |
| `!!` | à corriger : instances copiées au lieu de géométries références, couleur sans aucun dimmer, géométrie orpheline |
| `--` | info : références existantes, canaux virtuels, géométries similaires à vérifier |

## Tests

```
pip install pytest
python -m pytest
```

## Étape 2 : interface graphique (en cours, affichage seulement)

```
pip install -e .[gui]
ma3lib-gui                                   # ou : python -m ma3lib.gui
ma3lib-gui source.gdtf cible.xml             # ouvre directement deux fichiers
```

- En haut : Source et Cible (GDTF ou XML MA3, ou glisser le fichier sur la moitié voulue)
  et leur mode. Rien d'autre.
- Au centre : les instances en escalier, comme le SubfixtureOverview / Fixture Hero
  de MA3 (1, 1.1, 1.1.1…). Les lignes relient chaque instance cible à son instance source,
  proposées au chargement d'après les attributs communs. On tire une ligne pour rebrancher,
  clic droit pour débrancher, flèche pour replier.
- Double-clic sur une liaison : les attributs de la paire, avec pastilles et Coarse/Fine.
  Vert = des deux côtés, orange = perdu (source) ou absent (cible), jaune = remplacé,
  bleu = virtuel.
- En bas : légende et nombre d'instances cible branchées.

Captures : `docs/captures/`. Pas encore de sauvegarde ni d'écriture du fixture.
