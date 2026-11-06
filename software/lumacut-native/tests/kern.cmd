@echo off
rem Baut und prueft nur den Kern, eigener Ordner build-kern. Aufruf: tests\kern.cmd [Ziel] [ctest-Regex]
setlocal
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set VSPATH=%%i
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if "%QT_ROOT%"=="" set QT_ROOT=C:\Qt\6.10.3\msvc2022_64
pushd "%~dp0.."
if not exist build-kern\build.ninja cmake -S . -B build-kern -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=%QT_ROOT% || exit /b 1
set TARGET=%~1
if "%TARGET%"=="" set TARGET=test_golden test_core test_speed
cmake --build build-kern --target %TARGET%
if errorlevel 1 goto fail
if "%~2"=="" goto done
ctest --test-dir build-kern -R %~2 --output-on-failure
if errorlevel 1 goto fail
:done
popd
exit /b 0
:fail
popd
exit /b 1
