@echo off
title 86NocConnector - Setup
echo ============================================================
echo   86NocConnector - Preparazione ambiente
echo ============================================================
echo.

set "BASE_DIR=%~dp0"
set "PYTHON_DIR=%BASE_DIR%python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

:: Check if already extracted
if exist "%PYTHON_EXE%" (
    echo [OK] Python gia' pronto.
    goto install_deps
)

echo [1/2] Estrazione Python (incluso nel pacchetto)...

if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"

:: Extract embedded Python from included zip
if exist "%BASE_DIR%python-embedded.zip" (
    powershell -Command "& {Expand-Archive -Path '%BASE_DIR%python-embedded.zip' -DestinationPath '%PYTHON_DIR%' -Force}"
    echo   Python estratto con successo.
) else (
    echo [ERRORE] File python-embedded.zip non trovato nella cartella!
    echo   Assicurati che il file sia presente nella stessa cartella di setup.bat
    pause
    exit /b 1
)

:: Enable pip in embedded Python
powershell -Command "& {(Get-Content '%PYTHON_DIR%\python311._pth') -replace '#import site','import site' | Set-Content '%PYTHON_DIR%\python311._pth'}"

:: Install pip from get-pip (small download ~2MB)
echo [2/2] Installazione componenti aggiuntivi...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py'}" 2>nul
"%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location >nul 2>&1

:install_deps
:: Install only necessary lightweight packages
"%PYTHON_EXE%" -m pip install requests pystray Pillow --no-warn-script-location -q 2>nul

echo.
echo ============================================================
echo   Setup completato!
echo   Esegui install.bat per installare 86NocConnector
echo ============================================================
echo.
pause
