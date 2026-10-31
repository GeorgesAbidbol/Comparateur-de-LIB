# Notes GDTF utiles au projet

Sources : spec GDTF 1.2 (github.com/mvrdevelopment/spec) et aide GDTF Share
(https://gdtf-share.com/help/), lue le 31/10/2026.

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
