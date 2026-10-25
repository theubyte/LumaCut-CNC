@echo off
echo Building LumaCut Studio...
pip install -r requirements.txt
pip install pyinstaller
rem Scan/Probe: main.py importiert scanprobe.panel statisch, PyInstaller findet alle
rem scanprobe-Module (inkl. Funktions-Imports). --collect-submodules ist nur Absicherung;
rem lumacut_materials: --collect-data packt materials.json mit ein.
rem OpenCV (cv2) und numpy bringen eigene PyInstaller-Hooks mit.
pyinstaller --windowed --name LumaCutStudio --clean --noconfirm --paths src --collect-submodules scanprobe --collect-submodules lumacut_materials --collect-data lumacut_materials src/main.py
echo.
echo Fertig: dist\LumaCutStudio\LumaCutStudio.exe
pause
