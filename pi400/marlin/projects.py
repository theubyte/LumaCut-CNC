"""Saved projects on the Pi: every app can store and open them by name.

The workspace (workspace.py) holds the one project that is open right now;
this is the shelf next to it. One file per project in ``projects/`` plus
``index.json`` with the list (name, size, when and from which device).
Saving under a name that already exists replaces that project (the apps
ask first), names compare without case.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

MAX_PROJECT_BYTES = 30 * 1024 * 1024
MAX_PROJECTS = 200
MAX_NAME = 80


class NotFoundError(KeyError):
    pass


def _summary(doc: dict) -> dict:
    """Counts the list shows without loading the project."""
    elements = doc.get("elements")
    layers = doc.get("layers")
    return {"elements": len(elements) if isinstance(elements, list) else 0,
            "layers": len(layers) if isinstance(layers, list) else 0,
            "plates": doc.get("plateCount") if isinstance(doc.get("plateCount"), int) else 1}


class ProjectStore:
    def __init__(self, folder: Path):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        try:
            data = json.loads((self.dir / "index.json").read_text("utf-8"))
            self.index = [p for p in data.get("projects", []) if isinstance(p, dict) and (self.dir / self._file(p["id"])).is_file()]
        except Exception:
            self.index = []

    @staticmethod
    def _file(project_id: str) -> str:
        return project_id + ".json"

    def _write(self, name: str, data: bytes):
        tmp = self.dir / (name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.dir / name)

    def _save_index(self):
        self._write("index.json", json.dumps({"projects": self.index}, ensure_ascii=False).encode("utf-8"))

    def _find(self, project_id: str) -> dict:
        for p in self.index:
            if p["id"] == project_id:
                return p
        raise NotFoundError(project_id)

    def list(self) -> list[dict]:
        with self.lock:
            return sorted((dict(p) for p in self.index), key=lambda p: p["updated_at"], reverse=True)

    def get(self, project_id: str) -> tuple[dict, bytes]:
        with self.lock:
            meta = dict(self._find(project_id))
            return meta, (self.dir / self._file(project_id)).read_bytes()

    def save(self, name, raw: bytes, by: str = "") -> dict:
        """Stores ``raw`` (project JSON as the apps write it) under ``name``; same name = replaced."""
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME:
            raise ValueError("Projektname: 1 bis %d Zeichen" % MAX_NAME)
        name = " ".join(name.split())
        if len(raw) > MAX_PROJECT_BYTES:
            raise ValueError("Projekt größer als %d MB" % (MAX_PROJECT_BYTES // (1024 * 1024)))
        try:
            doc = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("Projekt ist kein gültiges JSON")
        if not isinstance(doc, dict) or not isinstance(doc.get("layers"), list) or not isinstance(doc.get("elements"), list):
            raise ValueError("Kein LumaCut-Projekt (layers und elements fehlen)")
        with self.lock:
            same = next((p for p in self.index if p["name"].casefold() == name.casefold()), None)
            if same is None and len(self.index) >= MAX_PROJECTS:
                raise ValueError("Schon %d Projekte auf dem Pi – erst alte löschen" % MAX_PROJECTS)
            meta = same or {"id": uuid.uuid4().hex}
            meta.update(name=name, bytes=len(raw), updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        updated_by=(by or "")[:40], **_summary(doc))
            self._write(self._file(meta["id"]), raw)
            if same is None:
                self.index.append(meta)
            self._save_index()
            return dict(meta, replaced=same is not None)

    def delete(self, project_id: str) -> None:
        with self.lock:
            meta = self._find(project_id)
            self.index.remove(meta)
            self._save_index()
            try:
                (self.dir / self._file(project_id)).unlink()
            except FileNotFoundError:
                pass


def create_blueprint(store: ProjectStore) -> Blueprint:
    bp = Blueprint("projects", __name__)

    @bp.errorhandler(NotFoundError)
    def not_found(_exc):
        return jsonify(error="Projekt nicht gefunden"), 404

    @bp.get("/api/projects")
    def projects_list():
        return jsonify(projects=store.list())

    @bp.get("/api/projects/<project_id>")
    def project_get(project_id):
        _meta, data = store.get(project_id)
        return data, 200, {"Content-Type": "application/json; charset=utf-8"}

    @bp.post("/api/projects")
    def project_save():
        # name in the query (?name=…&by=…), the body is the project JSON as is
        return jsonify(project=store.save(request.args.get("name", ""), request.get_data(), request.args.get("by", "")))

    @bp.delete("/api/projects/<project_id>")
    def project_delete(project_id):
        store.delete(project_id)
        return jsonify(message="Projekt gelöscht")

    return bp
