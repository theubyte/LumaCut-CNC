"""PyInstaller-Build für LumaCut Studio (eine Quelle für build-windows.bat und CI).

Aufruf: ``python build_exe.py`` im Ordner ``software/lumacut-studio-native``.
Ergebnis: ``dist/LumaCutStudio/LumaCutStudio.exe`` (bzw. ohne .exe auf Linux).

Warum die Optionen:
- ``--paths src``: Pakete liegen unter ``src``.
- ``--collect-submodules`` für alle eigenen Pakete: viele Module werden erst
  im Dialog geladen (lazy import), PyInstaller sähe sie sonst nicht.
- ``--collect-data lumacut_materials``: Materialbibliothek ``materials.json``.
  Dafür muss ``src`` schon beim Aufruf im ``sys.path`` liegen – sonst
  überspringt PyInstaller ``--collect-data``/``--collect-submodules`` nur mit
  einer Warnung („not a package“) und ``materials.json`` fehlt in der .exe.
- svgelements, ezdxf, pypdf (SVG-/DXF-/PDF-Import) werden lazy geladen
  (PyInstaller findet auch Importe in Funktionen; ezdxf lädt zusätzlich
  dynamisch, daher ``--collect-submodules ezdxf``).
- shapely (Kerf, Lead-Kollision), OpenCV (cv2) und numpy bringen eigene
  PyInstaller-Hooks mit (``--collect-submodules shapely`` würde die
  Testsuite mitpacken).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

OWN_PACKAGES = (
    "lumacut_canvas", "lumacut_import", "lumacut_job", "lumacut_materials",
    "lumacut_session", "lumacut_workflow", "machine", "scanprobe",
)
THIRD_PARTY = ("ezdxf",)
HIDDEN = ("svgelements", "pypdf", "shapely")


def pyinstaller_args() -> list[str]:
    args = ["--windowed", "--name", "LumaCutStudio", "--clean", "--noconfirm",
            "--paths", str(HERE / "src")]
    for pkg in OWN_PACKAGES + THIRD_PARTY:
        args += ["--collect-submodules", pkg]
    args += ["--collect-data", "lumacut_materials", "--collect-data", "ezdxf"]
    for mod in HIDDEN:
        args += ["--hidden-import", mod]
    args.append(str(HERE / "src" / "main.py"))
    return args


def bundled_files() -> list[Path]:
    """Dateien, die im fertigen Build liegen müssen (CI prüft sie)."""
    root = HERE / "dist" / "LumaCutStudio"
    internal = root / "_internal"
    return [internal / "lumacut_materials" / "materials.json"]


def check_bundle() -> int:
    missing = [p for p in bundled_files() if not p.exists()]
    for p in missing:
        print(f"FEHLT im Build: {p}")
    return 1 if missing else 0


def main(argv: list[str]) -> int:
    if "--check" in argv:
        return check_bundle()
    import PyInstaller.__main__  # erst hier: Tests brauchen PyInstaller nicht

    src = str(HERE / "src")
    if src not in sys.path:
        sys.path.insert(0, src)  # damit --collect-data/-submodules die Pakete finden
    PyInstaller.__main__.run(pyinstaller_args())
    return check_bundle()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
