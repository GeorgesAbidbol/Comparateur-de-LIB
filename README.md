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

Captures : `docs/captures/`.

Atelier géométries (étape 3, en cours) : `python -m ma3lib.gui.atelier fichier.gdtf [mode]`.
Arbre complet du mode avec les numéros de sélection MA3 (1.x.x.x), les géométries 3D seules
et les modèles en double, et les paramètres de la géométrie choisie (lecture seule pour
l'instant). **Glisser-déposer** : lâcher sur le milieu d'une ligne = enfant, sur le haut ou
le bas = avant / après ; Ctrl/Maj pour plusieurs ; les numéros se recalculent en direct ;
Ctrl+Z annule. Le déplacement suit dans l'XML d'origine (et les chemins des canaux MA3).
Clic droit : **regrouper** des géométries identiques (copies) en un modèle + des références
(même nom, même position, mêmes adresses : la console voit les mêmes instances) et
**fusionner** les modèles en double d'un mode à l'autre. Les copies à regrouper sont
marquées « copie ×N ». **Dupliquer** une référence N fois à adresses contiguës (pas proposé
d'après le modèle, un par jeu d'adresses comme sur l'iTetra2 ; alerte si une copie tombe sur
des adresses déjà prises). Sous l'arbre du mode, ses **modèles** (« modèle ×N ») : ce qu'on y range vaut pour toutes
leurs références (ex. pixels rangés sous le master une fois pour A et B). On range à
l'intérieur d'un même arbre. **Double-clic** : popup nom / type / adresse (un champ par jeu
d'adresses d'une référence, ou premier canal dans le mode) / grille (proposée d'après la 3D).
Regrouper, fusionner et dupliquer : GDTF seulement pour l'instant.

## Lancer sous Windows

Une seule appli : double-clic sur `Comparateur de LIB.bat`. Le premier lancement installe
Python 3.12 avec winget s'il manque, crée `.venv` et installe PySide6. La fenêtre a une section
par outil (Atelier, Comparateur) ; les prochains outils s'y ajouteront. On peut glisser un
`.gdtf` ou un `.xml` sur le lanceur pour l'ouvrir dans l'atelier. Ailleurs : `python -m ma3lib.gui`.

## Étape 4 : exporter pour grandMA3 2.3.2.0

Bouton **Exporter…** en bas de l'atelier : nom, note (ex. « JO »), GUID (gardé, ou nouveau
dès que le nom change), destination (onPC ou clé USB trouvées, à côté de l'original, ou un
dossier). Fichier `fabricant@nom.xml`, au format XML MA3 2.3.2.0 comme un export « User » de
la console : un GDTF est converti (règles dans `docs/ma3-xml-notes.md`), un XML MA3 est
réécrit tel quel avec les modifications de l'atelier.

```
python -m ma3lib export fichier.gdtf --dossier D:\lib [--nom "…" --note JO --nouveau-guid --remplacer]
python -m ma3lib export fichier.gdtf --onpc        # ou --cle
```
