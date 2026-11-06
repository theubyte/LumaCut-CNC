@echo off
rem Baut die App mit MSVC und Ninja. Aufruf: tools\build.cmd [Release|Debug] [Ziel]
setlocal
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set VSPATH=%%i
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if "%QT_ROOT%"=="" set QT_ROOT=C:\Qt\6.10.3\msvc2022_64
set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=Release
pushd "%~dp0.."
if not exist build\build.ninja cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=%CONFIG% -DCMAKE_PREFIX_PATH=%QT_ROOT% || exit /b 1
if "%~2"=="" (cmake --build build) else (cmake --build build --target %~2)
set RC=%ERRORLEVEL%
popd
exit /b %RC%
