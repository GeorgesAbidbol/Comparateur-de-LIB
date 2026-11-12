# Notes GDTF utiles au projet

Sources : spec GDTF 1.2 (github.com/mvrdevelopment/spec) et aide GDTF Share
(https://gdtf-share.com/help/), lue le 31/10/2026.

## Géométrie, géométrie référence, type de géométrie (règles de Jo, 10/11/2026)

Trois notions à ne pas mélanger :

- **Géométrie** : un nœud de l'arbre physique du fixture (nom unique). Elle peut porter
  des canaux ; sur la console, une géométrie qui porte des canaux devient une instance
  (1.x.x). Les niveaux sans canal se fondent dans le parent.
- **Type de géométrie** : la balise du nœud (`Geometry`, `Axis`, `Beam`, `FilterColor`…).
  Il dit *ce qu'est* la pièce : `Axis` bouge (pan / tilt), `Geometry` est un contenant
  (ex. la tête), `Beam` est la sortie de lumière. **Le `Beam` ne sert qu'à la 3D et à la
  simulation de lumière** : sur la console il ne porte rien, ce sont la tête (ou le
  segment, le pixel…) qui portent Dimmer, couleur, strobe… Le Beam est en général un
  enfant sans canal de cette géométrie. Il ne faut pas le supprimer (on perdrait la
  lumière en 3D), mais il ne crée pas d'instance.
- **Géométrie référence** (`GeometryReference`) : **un exemplaire de plus d'un même type
  d'instance**. Dès qu'un même type d'instance se répète, on décrit une seule fois le
  modèle (géométrie de premier niveau, avec ses enfants et ses canaux en adresses
  relatives) et on le pose N fois par des références, chacune avec son `<Break DMXOffset>`.
  Ce n'est **pas lié au pixel** : à n'importe quel étage. Exemples de Jo :
  masters de segment A et B du JDC Line 1000 (même type d'instance → un modèle, deux
  références), un projecteur à 12 têtes tilt → un seul modèle de tête, 12 références,
  2 × 20 pixels RGBW → un modèle de pixel, références à adresses contiguës.
  Une référence n'a pas d'enfant à elle : ce qui est « sous » elle sur la console vient
  de son modèle, et son type est celui de la racine du modèle.

Un seul arbre pour plusieurs modes (méthode de l'iTetra2, la bonne selon Jo) : chaque
référence de pixel a **deux Break**, `DMXBreak="1" DMXOffset="5"` puis `DMXBreak="1"
DMXOffset="4"` (P02). Le mode choisit par ses canaux : en RGBW (pas de 4) les canaux du
modèle sont en `DMXBreak="1"` → premier Break ; en RGB (pas de 3) ils sont en
`DMXBreak="Overwrite"` → dernier Break (règle de la spec). Les adresses des pixels sont
donc dans les références, le mode ne fait que choisir laquelle.

Conséquences pour l'atelier : regrouper des géométries identiques en modèle + références,
dupliquer une référence N fois à adresses contiguës, et pouvoir ranger (glisser-déposer)
aussi à l'intérieur des modèles.

## Pourquoi les multi-instances sont souvent mal faites

Dans le GDTF Builder, **« Duplicate » / « Multiple Duplication » crée des copies**
de la géométrie et de ses enfants, numérotées (`Pixel_1`, `Pixel_2`…), au même
niveau de l'arbre. Ce ne sont **pas** des géométries références. C'est le chemin
le plus simple dans l'outil, d'où les librairies copiées qu'on rencontre.

La bonne méthode (spec, `GeometryReference`) :
- un **modèle au premier niveau** (seules les géométries racine peuvent être référencées) ;
- les canaux DMX du modèle sont posés sur le modèle avec `DMXBreak="Overwrite"` ;
- chaque `GeometryReference` porte un `<Break DMXOffset="…" DMXBreak="…"/>`
  par break utilisé par le modèle.

Variante vue sur le Chauvet Color Strike M : des enveloppes `Group_N` contenant
une référence sans canaux. La référence ne sert qu'au visuel 3D.

## Dimmer virtuel : la recette officielle

Aide GDTF Share (« Create Virtual Channels ») et spec, listing 1 :
1. canal `Dimmer` **sans adresse** (`Offset="None"`, « Resolution : Virtual »),
   sur la géométrie qui porte les couleurs (ou un parent : les attributs descendent l'arbre) ;
2. **Highlight à 100 %** (`Highlight="255/1"`) ;
3. canal logique `Master="Grand"` (« React to Master ») ;
4. **une relation `Multiply` par canal de couleur additive** :
   `<Relation Name="VirtualDimmer" Master="Pixel_Dimmer" Follower="Pixel_ColorAdd_R.ColorAdd_R.ColorAdd_R 1" Type="Multiply"/>`

À contrôler dans le diagnostic (étape 3) : relation manquante pour une couleur,
Highlight absent, Master pas à Grand.

## Autres points

- Une géométrie racine = point de montage (base, lyre). Les positions des enfants
  sont relatives au parent.
- Le nom d'un canal DMX n'est pas libre : `<Géométrie>_<Attribut du 1er canal logique>`,
  unique dans le mode. À respecter quand on renomme/convertit.
- Dépendances de mode (`ModeMaster`, `ModeFrom`, `ModeTo`) : à préserver telles
  quelles quand on modifie un canal, elles pointent vers d'autres canaux par nom.
- Max recommandé : 1200 sommets pour les modèles 3D de tout le fixture.

## Référence de qualité : Robe Lighting (choix de Jo)

Les GDTF Robe servent d'étalon. Exemple Robin Esprite (GDTF 1.2) :

```
1 (2)  Base [Geometry]            canaux généraux (Control1, vitesses, LEDFrequency…)
  1 (1)  Yoke [Axis]              Pan
    1 (1)  Head [Axis]            Tilt + toutes les fonctions optiques + Dimmer
      1      Beam [Beam]          aucun canal : retiré par « Retirer la 3D »
  2 (6)  Pigtail [Geometry]       connecteurs (WiringObject) : pur 3D
```

- Noms de géométries courts et en anglais : Base, Yoke, Head, Beam.
- Canaux nommés `<Géométrie>_<Attribut>` (Yoke_Pan, Head_Tilt).
- Un mode = une racine (Base), pas de copie d'arbre par mode.
- Connecteurs regroupés sous un « Pigtail ».

**Règle de Jo (10/11/2026)** : la 3D ne l'intéresse pas, elle encombre les librairies, la
lecture des géométries et le patch des références. « Retirer la 3D » (atelier,
`geotree.strip_3d`) supprime toute géométrie qui ne porte aucun canal dans les modes qui
l'utilisent : Beams vides, câblage, références de pixels sans canal (ex. les 19 LED du mode
Standard du Nando 502, qui gardent leurs canaux en mode Pixel). Canaux et adresses ne bougent pas.

À vérifier : comment MA3 présente les Axis (Yoke/Head) dans le SubfixtureOverview.

### Modèle multi-instances : Robe iTetra2 (« propre » selon Jo)

```
Base                         canaux généraux
  Head [Axis]                Tilt, Zoom, Shutter, Dimmer
    Background               overall : Color1, RGBW, CTO, Shutter, Dimmer
      All pixels             (sans canal : fusionné par MA3)
        Zoom 1               Zoom de la zone 1
          P01…P09  -> Lens Pixel   (références, Break par pixel)
        Zoom 2               Zoom de la zone 2
          P10…P18  -> Lens Pixel
    P5 Flower / P14 Flower -> Lens Flower Pixel
    Pattern
  Pigtail, Pigtail 1         connecteurs : seuls éléments à supprimer
Lens Pixel [Beam]            modèle unique, Dimmer virtuel + couleurs
Lens Flower Pixel [Beam]
```

- **Un seul arbre pour les 6 modes**, un seul modèle de pixel (Lens Pixel) :
  exactement la règle de Jo.
- Les zones (Zoom 1 / Zoom 2) regroupent de vrais pixels références : ce ne sont
  pas des « copies » à convertir (corrigé dans le diagnostic).
- `ma3lib check` ne relève que les deux Pigtails.

## Une base par mode (règle de Jo, 11/11/2026)

Pour un fixture **multi-instances**, chaque mode a sa propre base : « souvent les
arborescences ne sont pas les mêmes » d'un mode à l'autre (8 bits, pixel, 2U). Un arbre
partagé oblige à plusieurs Breaks par référence et à `DMXBreak="Overwrite"` (iTetra2), ce qui
brouille le patch des références.

Ce qui reste commun : **les briques**. Même modèle de base, d'axis, de head, de pixel, et
mêmes modèles de référence d'un mode à l'autre. Cette règle remplace « un seul arbre pour
tous les modes » ; elle garde « on réutilise les mêmes modèles ».

Atelier : bouton « Une base par mode » (`geotree.split_per_mode`, GDTF). Le premier mode
garde l'arbre d'origine, les autres reçoivent une copie ; toutes les géométries prennent en
suffixe le nom du mode donné par le fabricant (`Base Mode 3-Pixel RGB`, choix de Jo) ; chaque
référence ne garde que les Breaks de son mode ; canaux, liens et adresses suivent. Un fixture
sans sous-instance (Esprite) garde sa base unique. Ensuite « Retirer la 3D » élague chaque
base selon son mode.
