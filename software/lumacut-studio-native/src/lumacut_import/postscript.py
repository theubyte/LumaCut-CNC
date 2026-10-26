"""EPS- und AI-Import über PDF (Qt-frei).

* **AI** (Adobe Illustrator ab Version 9) ist intern ein PDF – solche Dateien
  gehen direkt an den PDF-Import (``pdf.py``, nur pypdf, BSD-Lizenz).
* **EPS** und alte AI-Dateien (Illustrator ≤ 8, reines PostScript) brauchen
  einen PostScript-Interpreter. Ist **Ghostscript** installiert, wandelt er die
  Datei mit ``-dEPSCrop`` (Seite = BoundingBox) in ein temporäres PDF um, das
  dann wie jedes PDF importiert wird. Ohne Ghostscript gibt es eine klare
  deutsche Meldung, was zu tun ist – nie einen stillen Fehler.

Ghostscript wird nicht mitgeliefert (AGPL); gesucht wird in dieser
Reihenfolge: Umgebungsvariable ``LUMACUT_GHOSTSCRIPT``, ``gswin64c``,
``gswin32c``, ``gs`` im PATH, unter Windows ``C:\\Program Files\\gs\\*\\bin``.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

GS_TIMEOUT_S = 120
GS_NAMES = ("gswin64c", "gswin32c", "gs")
GS_MISSING = ("{kind}-Import braucht Ghostscript (kostenlos: ghostscript.com → "
              "„Ghostscript AGPL Release“ für Windows installieren, danach LumaCut "
              "neu starten). Alternative: die Datei im Grafikprogramm als SVG oder "
              "PDF speichern und das importieren.")


def sniff(path) -> str:
    """Dateiart nach Inhalt: ``"pdf"``, ``"ps"``, ``"eps-dos"`` oder ``"?"``."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError as exc:
        raise ValueError(f"Datei nicht lesbar: {exc}") from exc
    if head[:4] == b"\xc5\xd0\xd3\xc6":
        return "eps-dos"  # DOS-EPS mit TIFF/WMF-Vorschau
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.lstrip()[:2] == b"%!":
        return "ps"
    return "?"


def find_ghostscript() -> str | None:
    env = os.environ.get("LUMACUT_GHOSTSCRIPT", "").strip()
    if env and os.path.isfile(env):
        return env
    for name in GS_NAMES:
        hit = shutil.which(name)
        if hit:
            return hit
    if sys.platform.startswith("win"):
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            hits = sorted(glob.glob(os.path.join(root, "gs", "*", "bin", "gswin*c.exe")))
            if hits:
                return hits[-1]  # neueste Version
    return None


def ps_to_pdf(src, dst, kind: str = "EPS", gs: str | None = None) -> None:
    """PostScript/EPS → PDF mit Ghostscript; ValueError mit deutscher Meldung."""
    gs = gs or find_ghostscript()
    if not gs:
        raise ValueError(GS_MISSING.format(kind=kind))
    cmd = [gs, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sDEVICE=pdfwrite",
           "-dEPSCrop", f"-sOutputFile={os.fspath(dst)}", os.fspath(src)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=GS_TIMEOUT_S,
                              creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{kind}-Umwandlung dauerte zu lange (über {GS_TIMEOUT_S} s)") from exc
    except OSError as exc:
        raise ValueError(f"Ghostscript ließ sich nicht starten: {exc}") from exc
    if proc.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        msg = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        raise ValueError(f"{kind} nicht lesbar (Ghostscript: {msg[:200] or proc.returncode})")


def load_postscript(path, page: int = 0, kind: str = "EPS"):
    """EPS/AI → VectorImport. AI mit PDF-Kern ohne Ghostscript."""
    from .pdf import load_pdf

    what = sniff(path)
    if what == "pdf":
        return load_pdf(path, page)
    if what not in ("ps", "eps-dos"):
        raise ValueError(f"Keine gültige {kind}-Datei (weder PDF- noch PostScript-Inhalt)")
    with tempfile.TemporaryDirectory(prefix="lumacut-ps-") as tmp:
        out = os.path.join(tmp, "import.pdf")
        ps_to_pdf(path, out, kind)
        return load_pdf(out, page)
