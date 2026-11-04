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

## Points à vérifier sur le matériel de Jo

- [x] Clé USB : `<lecteur>:\grandMA3\gma3_library\fixturetypes` (confirmé par Jo).
- [x] onPC : `C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes` (confirmé par Jo).
- [ ] Connexion GDTF Share réelle (non testable depuis l'environnement de dev).
- [ ] Comment MA3 2.3.2.0 affiche un dimmer virtuel ajouté dans un GDTF.
- [ ] Une géométrie Axis (tête qui bascule) se fond dans l'instance du dessus : vu sur
  l'iTetra2 (Tilt porté par le fixture). À confirmer sur un fixture à plusieurs têtes.
