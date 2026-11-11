@echo off
rem Lance le comparateur. Premier lancement : cree .venv et installe PySide6 (Python 3.10+ requis).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Premiere installation, une a deux minutes...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Python est introuvable. Installe Python 3.12 depuis python.org ^(coche "Add python.exe to PATH"^) puis relance.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -e ".[gui]"
    if errorlevel 1 (
        echo L'installation a echoue ^(connexion internet ?^).
        pause
        exit /b 1
    )
)
start "" ".venv\Scripts\pythonw.exe" -m ma3lib.gui %*
