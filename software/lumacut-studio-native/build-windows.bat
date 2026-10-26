@echo off
echo Building LumaCut Studio...
pip install -r requirements.txt
pip install pyinstaller
rem Alle PyInstaller-Optionen (eigene Pakete, Materialdaten, SVG/DXF/PDF-Import,
rem shapely) stehen in build_exe.py - dieselbe Quelle nutzt auch die Windows-CI.
python build_exe.py
if errorlevel 1 (
  echo Build fehlgeschlagen.
  pause
  exit /b 1
)
echo.
echo Fertig: dist\LumaCutStudio\LumaCutStudio.exe
pause
