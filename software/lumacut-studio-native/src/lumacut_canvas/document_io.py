"""Projektdateien laden und speichern (JSON, UTF-8, Endung .lumacut.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import Document

FILE_SUFFIX = ".lumacut.json"


def save_document(doc: Document, path: str | os.PathLike[str]) -> Path:
    """Schreibt atomar (temporäre Datei + Umbenennen), damit ein Absturz
    beim Speichern keine halbe Projektdatei hinterlässt."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def load_document(path: str | os.PathLike[str]) -> Document:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Document.from_dict(data)


def load_into(doc: Document, path: str | os.PathLike[str]) -> None:
    """Lädt in ein bestehendes Dokument (Listener bleiben erhalten)."""
    doc.load_dict(json.loads(Path(path).read_text(encoding="utf-8")))
