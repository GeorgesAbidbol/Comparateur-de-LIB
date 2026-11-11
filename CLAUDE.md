# Banane Pot (dépôt Comparateur de LIB) — notes pour Claude

Appli de bureau Python (paquet `src/ma3lib`) pour les librairies GDTF de grandMA3.
Usage personnel de Jo, programmeur grandMA en tournée (gros parcs, 800+ fixtures).

- Version cible : **grandMA3 2.3.2.0** uniquement (Jo ne passe pas en 2.4+).
- Référence du format : spec GDTF 1.2, https://github.com/mvrdevelopment/spec (gdtf-spec.md).
- Fixture Fix (grandMA2) sert de modèle **fonctionnel** uniquement, à partir de captures
  d'écran. Ne jamais versionner ni décompiler son installeur.
- Identifiants GDTF Share : jamais dans un fichier ni dans le dépôt. Seule exception (choix de Jo,
  11/11/2026) : le coffre de Windows via `keyring` (`ma3lib.coffre`), pour « Rester connecté ».
- Toute modification de GDTF doit préserver ce qu'on ne comprend pas
  (on garde l'arbre XML d'origine dans `FixtureType.xml_root`).
- Plan et points à vérifier : `docs/plan.md`. Tester avec `python -m pytest`.
- Version : `__version__` dans `src/ma3lib/__init__.py` (et `pyproject.toml`), affichée dans le titre
  des fenêtres. **L'incrémenter à chaque zip livré à Jo** (`Banane-Pot-v<version>.zip`).
- **Une seule appli** (Jo, 11/11/2026) : tout outil est une section de `gui/app.py` (AppWindow),
  jamais un programme ou un lanceur à part.
- Nom de l'appli : **Banane Pot** (`ma3lib.APP_NAME`), partout où l'utilisateur le voit.
