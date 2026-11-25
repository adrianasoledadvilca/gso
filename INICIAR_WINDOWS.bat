@echo off
chcp 65001 >nul
title GSO - Gestion de Stock Odontologico
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  No se encontro Python. Instalelo desde https://www.python.org/downloads/
  echo  y marque la opcion "Add Python to PATH" durante la instalacion.
  pause
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  echo Preparando el sistema por primera vez, espere...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" app.py
pause
