@echo off
set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python\python.exe"
start "" "%PYTHON_EXE%" "%BASE_DIR%src\tray_app.py"
