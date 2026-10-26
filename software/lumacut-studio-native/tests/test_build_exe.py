"""PyInstaller-Optionen (build_exe.py) decken alle Pakete und Daten ab."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "build_exe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_src_package_is_collected():
    b = _build()
    pkgs = {p.name for p in (ROOT / "src").iterdir() if (p / "__init__.py").exists()}
    assert pkgs <= set(b.OWN_PACKAGES), f"neues Paket fehlt in build_exe.py: {pkgs - set(b.OWN_PACKAGES)}"
    args = b.pyinstaller_args()
    for pkg in b.OWN_PACKAGES:
        assert ("--collect-submodules", pkg) in zip(args, args[1:])
    assert ("--collect-data", "lumacut_materials") in zip(args, args[1:])
    for mod in ("svgelements", "pypdf", "shapely"):
        assert ("--hidden-import", mod) in zip(args, args[1:])
    assert args[-1].endswith("main.py")


def test_runtime_requirements_listed():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for dep in ("pyside6", "shapely", "ezdxf", "svgelements", "pypdf"):
        assert dep in req


def test_build_scripts_use_build_exe():
    bat = (ROOT / "build-windows.bat").read_text(encoding="utf-8")
    assert "python build_exe.py" in bat
    wf = ROOT.parents[1] / ".github" / "workflows" / "lumacut-studio-native.yml"
    if wf.exists():
        assert "build_exe.py" in wf.read_text(encoding="utf-8")


def test_bundle_check_reports_missing(tmp_path, monkeypatch):
    b = _build()
    monkeypatch.setattr(b, "HERE", tmp_path)
    assert b.check_bundle() == 1
    f = tmp_path / "dist" / "LumaCutStudio" / "_internal" / "lumacut_materials" / "materials.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    assert b.check_bundle() == 0
