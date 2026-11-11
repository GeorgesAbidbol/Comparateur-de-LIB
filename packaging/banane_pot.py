"""Point d'entrée de l'exe Windows (PyInstaller) : lance l'appli Banane Pot."""

import sys

from ma3lib.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
