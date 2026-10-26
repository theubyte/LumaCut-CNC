@echo off
echo Building LumaCut Studio...
pip install -r requirements.txt
pip install pyinstaller
rem Scan/Probe: main.py importiert scanprobe.panel statisch, PyInstaller findet alle
rem scanprobe-Module (inkl. Funktions-Imports). --collect-submodules ist nur Absicherung;
rem lumacut_materials: --collect-data packt materials.json mit ein.
rem Import: svgelements/ezdxf werden erst beim Import geladen (lazy) - darum explizit.
rem shapely (Kerf-Versatz im Planer) bringt einen Hook mit; --collect-submodules sichert ab.
rem OpenCV (cv2) und numpy bringen eigene PyInstaller-Hooks mit.
pyinstaller --windowed --name LumaCutStudio --clean --noconfirm --paths src --collect-submodules scanprobe --collect-submodules lumacut_materials --collect-data lumacut_materials --collect-submodules lumacut_import --collect-submodules lumacut_job --hidden-import svgelements --collect-submodules ezdxf --collect-data ezdxf --collect-submodules shapely src/main.py
echo.
echo Fertig: dist\LumaCutStudio\LumaCutStudio.exe
pause
