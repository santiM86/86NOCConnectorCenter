@echo off
title 86NocConnector - Setup
echo ============================================================
echo   86NocConnector - Preparazione ambiente
echo ============================================================
echo.

set "BASE_DIR=%~dp0"
set "PYTHON_DIR=%BASE_DIR%python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PIP_EXE=%PYTHON_DIR%\Scripts\pip.exe"

:: Check if Python embedded is already downloaded
if exist "%PYTHON_EXE%" (
    echo [OK] Python embedded gia' presente.
    goto install_deps
)

echo [1/3] Download Python embedded...
echo.

:: Create python dir
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"

:: Download Python 3.11 embedded
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile '%PYTHON_DIR%\python.zip'}"

if not exist "%PYTHON_DIR%\python.zip" (
    echo [ERRORE] Download Python fallito. Controlla la connessione internet.
    pause
    exit /b 1
)

echo [2/3] Estrazione Python...
powershell -Command "& {Expand-Archive -Path '%PYTHON_DIR%\python.zip' -DestinationPath '%PYTHON_DIR%' -Force}"
del "%PYTHON_DIR%\python.zip"

:: Enable pip in embedded Python
powershell -Command "& {(Get-Content '%PYTHON_DIR%\python311._pth') -replace '#import site','import site' | Set-Content '%PYTHON_DIR%\python311._pth'}"

:: Download get-pip.py
echo [2/3] Installazione pip...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py'}"
"%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location >nul 2>&1

:install_deps
echo [3/3] Installazione dipendenze...
"%PYTHON_EXE%" -m pip install requests pystray Pillow --no-warn-script-location -q 2>nul
if errorlevel 1 (
    "%PYTHON_DIR%\Scripts\pip.exe" install requests pystray Pillow --no-warn-script-location -q 2>nul
)

echo.
echo ============================================================
echo   Setup completato! 
echo   Esegui install.bat per installare 86NocConnector
echo ============================================================
echo.
pause
