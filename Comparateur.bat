@echo off
rem Lance le comparateur. Premier lancement : installe Python si besoin, cree .venv, installe PySide6.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run

echo Premiere installation, quelques minutes...
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY="%LocalAppData%\Programs\Python\Python312\python.exe""
if not defined PY (
    echo Python n'est pas installe : installation de Python 3.12 avec winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY="%LocalAppData%\Programs\Python\Python312\python.exe""
)
if not defined PY (
    echo.
    echo Python n'a pas pu etre installe automatiquement.
    echo Installe Python 3.12 depuis https://www.python.org/downloads/ ^(coche "Add python.exe to PATH"^) puis relance.
    pause
    exit /b 1
)
%PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo La creation de l'environnement a echoue.
    pause
    exit /b 1
)
echo Installation de l'interface ^(PySide6^)...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e ".[gui]"
if errorlevel 1 (
    echo L'installation a echoue ^(connexion internet ?^).
    rmdir /s /q .venv
    pause
    exit /b 1
)

:run
start "" ".venv\Scripts\pythonw.exe" -m ma3lib.gui %*
