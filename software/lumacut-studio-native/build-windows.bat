@echo off
echo Building LumaCut Studio...
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --windowed --name LumaCutStudio --clean --noconfirm src/main.py
echo.
echo Fertig: dist\LumaCutStudio\LumaCutStudio.exe
pause
