# Comparateur de LIB — notes pour Claude

Appli de bureau Python (paquet `src/ma3lib`) pour les librairies GDTF de grandMA3.
Usage personnel de Jo, programmeur grandMA en tournée (gros parcs, 800+ fixtures).

- Version cible : **grandMA3 2.3.2.0** uniquement (Jo ne passe pas en 2.4+).
- Référence du format : spec GDTF 1.2, https://github.com/mvrdevelopment/spec (gdtf-spec.md).
- Fixture Fix (grandMA2) sert de modèle **fonctionnel** uniquement, à partir de captures
  d'écran. Ne jamais versionner ni décompiler son installeur.
- Ne jamais écrire d'identifiants GDTF Share sur disque ni dans le dépôt.
- Toute modification de GDTF doit préserver ce qu'on ne comprend pas
  (on garde l'arbre XML d'origine dans `FixtureType.xml_root`).
- Plan et points à vérifier : `docs/plan.md`. Tester avec `python -m pytest`.
