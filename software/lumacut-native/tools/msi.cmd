@echo off
rem Baut die MSI lokal in einem Schritt: inkrementell bauen, Kern-Tests, packen.
rem   tools\msi.cmd            bauen, Kern-Tests, MSI
rem   tools\msi.cmd schnell    ohne Tests
rem   tools\msi.cmd fenster    zusaetzlich alle Fenster-Tests gegen den Simulator (Python mit flask in LUMACUT_PY oder im PATH)
rem Die Versionsnummer folgt derselben Regel wie die CI (Monat seit 12/2025, Tag und Minute in UTC),
rem damit jede neuere MSI die aeltere ersetzt, egal ob sie lokal oder von GitHub kommt.
setlocal
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set VSPATH=%%i
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if "%QT_ROOT%"=="" set QT_ROOT=C:\Qt\6.10.3\msvc2022_64
if "%WIX%"=="" set WIX=%LOCALAPPDATA%\tauri\WixTools314\
set PATH=%WIX%;%QT_ROOT%\bin;%PATH%
for /f "usebackq tokens=*" %%v in (`powershell -NoProfile -File "%~dp0version.ps1"`) do set VERSION=%%v
pushd "%~dp0.."
echo LumaCut Studio %VERSION%
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=%QT_ROOT% -DLUMACUT_VERSION=%VERSION% >nul || goto fail
cmake --build build || goto fail
if /i not "%~1"=="schnell" (
  ctest --test-dir build -LE speed --output-on-failure || goto fail
)
if "%LUMACUT_PY%"=="" set LUMACUT_PY=python
set PYTHONUTF8=1
if /i "%~1"=="fenster" "%LUMACUT_PY%" tests\ui\run_all.py || goto fail
cmake --build build --target package || goto fail
if not exist dist mkdir dist
copy /y build\LumaCut-Studio.msi "dist\LumaCut-Studio-%VERSION%.msi" >nul || goto fail
echo.
echo MSI fertig: %CD%\dist\LumaCut-Studio-%VERSION%.msi
popd
exit /b 0
:fail
echo.
echo FEHLER beim Bauen der MSI, siehe oben.
popd
exit /b 1
