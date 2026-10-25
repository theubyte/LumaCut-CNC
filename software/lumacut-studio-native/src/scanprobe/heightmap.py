"""Höhenmesh je Bereich und kombinierte Abfrage.

Jeder Bereich hat ein eigenes regelmäßiges Raster (``xs`` × ``ys``). Fehlende
Knoten (außerhalb des Umrisses, Fehlmessung) werden für die Abfrage aus den
gemessenen Nachbarn ergänzt und als ``INTERPOLATED`` markiert.

Abfrage bilinear oder bikubisch (Catmull-Rom). Außerhalb aller Bereiche
liefert ``HeightMapSet.surface_z`` ``None`` – der Aufrufer entscheidet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
import math
import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .geometry import Polygon, Rect

# Knotenstatus
NOT_PROBED = 0
MEASURED = 1
RETRIED = 2
INTERPOLATED = 3
FAILED = 4
OUTLIER = 5
STATUS_NAMES = {0: "not_probed", 1: "measured", 2: "retried", 3: "interpolated",
                4: "failed", 5: "outlier"}


@dataclass
class HeightMap:
    area_id: str
    polygon: Polygon
    xs: np.ndarray
    ys: np.ndarray
    z: np.ndarray            # (ny, nx), NaN = keine Messung
    status: np.ndarray       # (ny, nx) int8
    kind: str = "rectangle"
    edge_tolerance_mm: float = 6.0
    _filled: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        self.xs = np.asarray(self.xs, float)
        self.ys = np.asarray(self.ys, float)
        self.z = np.asarray(self.z, float).reshape(len(self.ys), len(self.xs))
        self.status = np.asarray(self.status, np.int8).reshape(self.z.shape)

    @classmethod
    def empty(cls, area_id: str, polygon: Polygon, xs, ys, kind="rectangle") -> "HeightMap":
        shape = (len(ys), len(xs))
        return cls(area_id, polygon, xs, ys, np.full(shape, np.nan), np.zeros(shape, np.int8), kind)

    # ------------------------------------------------------------------
    def set(self, i: int, j: int, z: Optional[float], status: int) -> None:
        self.z[j, i] = np.nan if z is None else z
        self.status[j, i] = status
        self._filled = None

    @property
    def valid(self) -> np.ndarray:
        return np.isin(self.status, (MEASURED, RETRIED)) & np.isfinite(self.z)

    @property
    def measured_count(self) -> int:
        return int(self.valid.sum())

    def filled(self) -> np.ndarray:
        """Raster ohne Lücken: Lücken per inverser Distanzgewichtung (k=4)."""
        if self._filled is not None:
            return self._filled
        v = np.isin(self.status, (MEASURED, RETRIED, INTERPOLATED)) & np.isfinite(self.z)
        if not v.any():
            raise ValueError(f"Bereich {self.area_id}: keine gültige Messung")
        X, Y = np.meshgrid(self.xs, self.ys)
        out = self.z.copy()
        px, py, pz = X[v], Y[v], self.z[v]
        for j, i in zip(*np.nonzero(~v)):
            d = np.hypot(px - X[j, i], py - Y[j, i])
            k = np.argsort(d)[:4]
            w = 1.0 / np.maximum(d[k], 1e-6) ** 2
            out[j, i] = float((w * pz[k]).sum() / w.sum())
        self._filled = out
        return out

    def contains(self, x: float, y: float, tolerance: Optional[float] = None) -> bool:
        tol = self.edge_tolerance_mm if tolerance is None else tolerance
        return self.polygon.contains(x, y) or self.polygon.edge_distance(x, y) <= tol

    def z_at(self, x: float, y: float, method: str = "bicubic") -> float:
        """Oberflächen-Z bei (x, y); außerhalb des Rasters flach fortgesetzt."""
        g = self.filled()
        nx, ny = len(self.xs), len(self.ys)
        fx = _frac_index(self.xs, x)
        fy = _frac_index(self.ys, y)
        if nx == 1 and ny == 1:
            return float(g[0, 0])
        if method == "bilinear":
            return float(_bilinear(g, fx, fy))
        if method == "bicubic":
            return float(_bicubic(g, fx, fy))
        if method == "nearest":
            return float(g[int(round(fy)), int(round(fx))])
        raise ValueError(f"Unknown method {method}")

    # ------------------------------------------------------------------
    def stats(self) -> dict:
        v = self.valid
        if not v.any():
            return {"points": 0}
        zz = self.z[v]
        X, Y = np.meshgrid(self.xs, self.ys)
        out = {"points": int(v.sum()), "min": float(zz.min()), "max": float(zz.max()),
               "mean": float(zz.mean()), "range": float(zz.max() - zz.min()),
               "failed": int((self.status == FAILED).sum()),
               "outliers": int((self.status == OUTLIER).sum()),
               "interpolated": int((self.status == INTERPOLATED).sum())}
        if v.sum() >= 3:
            A = np.c_[X[v], Y[v], np.ones(v.sum())]
            coef, *_ = np.linalg.lstsq(A, zz, rcond=None)
            resid = zz - A @ coef
            out["tilt_mm_per_100mm"] = (float(coef[0] * 100), float(coef[1] * 100))
            out["flatness_mm"] = float(resid.max() - resid.min())
        return out

    def to_dict(self) -> dict:
        return {"area_id": self.area_id, "kind": self.kind, "polygon": self.polygon.to_list(),
                "xs": self.xs.tolist(), "ys": self.ys.tolist(),
                "z": [[None if not math.isfinite(v) else round(float(v), 4) for v in row] for row in self.z],
                "status": self.status.tolist(), "edge_tolerance_mm": self.edge_tolerance_mm}

    @classmethod
    def from_dict(cls, d: dict) -> "HeightMap":
        z = np.array([[np.nan if v is None else v for v in row] for row in d["z"]], float)
        return cls(d["area_id"], Polygon(tuple(map(tuple, d["polygon"]))), d["xs"], d["ys"], z,
                   d["status"], d.get("kind", "rectangle"), d.get("edge_tolerance_mm", 6.0))


def _frac_index(axis: np.ndarray, v: float) -> float:
    if len(axis) == 1:
        return 0.0
    v = min(max(v, axis[0]), axis[-1])
    k = int(np.searchsorted(axis, v, side="right") - 1)
    k = min(max(k, 0), len(axis) - 2)
    return k + (v - axis[k]) / (axis[k + 1] - axis[k])


def _bilinear(g: np.ndarray, fx: float, fy: float) -> float:
    ny, nx = g.shape
    x0 = min(int(math.floor(fx)), max(nx - 2, 0))
    y0 = min(int(math.floor(fy)), max(ny - 2, 0))
    x1, y1 = min(x0 + 1, nx - 1), min(y0 + 1, ny - 1)
    a, b = fx - x0, fy - y0
    return ((1 - a) * (1 - b) * g[y0, x0] + a * (1 - b) * g[y0, x1]
            + (1 - a) * b * g[y1, x0] + a * b * g[y1, x1])


def _cr(p0, p1, p2, p3, t):
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


def _bicubic(g: np.ndarray, fx: float, fy: float) -> float:
    ny, nx = g.shape
    if nx < 3 or ny < 3:
        return _bilinear(g, fx, fy)
    x1 = min(int(math.floor(fx)), nx - 2)
    y1 = min(int(math.floor(fy)), ny - 2)
    tx, ty = fx - x1, fy - y1
    # Randknoten linear extrapolieren (statt klemmen) -> Ebenen/Neigung exakt
    gp = np.empty((ny + 2, nx + 2))
    gp[1:-1, 1:-1] = g
    gp[1:-1, 0] = 2 * g[:, 0] - g[:, 1]
    gp[1:-1, -1] = 2 * g[:, -1] - g[:, -2]
    gp[0] = 2 * gp[1] - gp[2]
    gp[-1] = 2 * gp[-2] - gp[-3]
    rows = []
    for dy in (0, 1, 2, 3):
        r = gp[y1 + dy]
        rows.append(_cr(r[x1], r[x1 + 1], r[x1 + 2], r[x1 + 3], tx))
    val = _cr(*rows, ty)
    # Überschwinger begrenzen: nie außerhalb der 4 Nachbarknoten ± 10 % Spanne
    nb = g[y1:y1 + 2, x1:x1 + 2]
    lo, hi = nb.min(), nb.max()
    pad = 0.1 * (hi - lo)
    return float(min(max(val, lo - pad), hi + pad))


@dataclass
class HeightMapSet:
    """Alle Bereichs-Meshes eines Auftrags + Fingerabdruck für Wiederverwendung."""
    maps: list[HeightMap]
    created: float = field(default_factory=time.time)
    material: str = ""
    fingerprints: dict = field(default_factory=dict)   # area_id -> {"bounds","size","data"}
    method: str = "bicubic"

    def map_for(self, x: float, y: float) -> Optional[HeightMap]:
        inside = [m for m in self.maps if m.polygon.contains(x, y)]
        if inside:
            return inside[0]
        near = [(m.polygon.edge_distance(x, y), m) for m in self.maps if m.contains(x, y)]
        return min(near, key=lambda t: t[0])[1] if near else None

    def surface_z(self, x: float, y: float, method: Optional[str] = None) -> Optional[float]:
        m = self.map_for(x, y)
        return None if m is None else m.z_at(x, y, method or self.method)

    def z_offset(self, x: float, y: float, reference_z: float = 0.0,
                 method: Optional[str] = None) -> Optional[float]:
        """Höhe relativ zu ``reference_z`` (z. B. Fokusebene des Jobs)."""
        z = self.surface_z(x, y, method)
        return None if z is None else z - reference_z

    def get(self, area_id: str) -> HeightMap:
        for m in self.maps:
            if m.area_id == area_id:
                return m
        raise KeyError(area_id)

    # ---- Wiederverwendung -------------------------------------------
    def add_fingerprints(self, mosaic, size: int = 64) -> None:
        """Bildausschnitt je Bereich merken, um später Verschieben zu erkennen."""
        import cv2
        for m in self.maps:
            patch = _patch(mosaic, m.polygon.bounds.expand(5), size)
            if patch is not None:
                self.fingerprints[m.area_id] = {
                    "bounds": m.polygon.bounds.expand(5).to_list(), "size": size,
                    "data": base64.b64encode(patch.tobytes()).decode("ascii")}

    def check_material_unchanged(self, mosaic, max_shift_mm: float = 0.5,
                                 min_similarity: float = 0.85) -> dict:
        """Vergleicht Fingerabdrücke mit neuem Mosaik.

        Rückgabe ``{area_id: {"ok": bool, "shift_mm": float, "similarity": float}}``.
        """
        import cv2
        out = {}
        for m in self.maps:
            fp = self.fingerprints.get(m.area_id)
            if not fp:
                out[m.area_id] = {"ok": False, "shift_mm": math.inf, "similarity": 0.0, "reason": "kein Fingerabdruck"}
                continue
            size = fp["size"]
            old = np.frombuffer(base64.b64decode(fp["data"]), np.uint8).reshape(size, size).astype(np.float32)
            b = Rect(*fp["bounds"])
            new = _patch(mosaic, b, size)
            if new is None:
                out[m.area_id] = {"ok": False, "shift_mm": math.inf, "similarity": 0.0, "reason": "außerhalb Scan"}
                continue
            new = new.astype(np.float32)
            (dx, dy), _ = cv2.phaseCorrelate(old, new, cv2.createHanningWindow((size, size), cv2.CV_32F))
            shift = math.hypot(dx * b.width / size, dy * b.height / size)
            a, c = old - old.mean(), new - new.mean()
            den = math.sqrt(float((a * a).sum() * (c * c).sum()))
            sim = float((a * c).sum() / den) if den > 0 else 0.0
            out[m.area_id] = {"ok": bool(shift <= max_shift_mm and sim >= min_similarity),
                              "shift_mm": shift, "similarity": sim}
        return out

    # ---- Persistenz -------------------------------------------------
    def to_dict(self) -> dict:
        return {"format": "lumacut-heightmaps/1", "created": self.created, "material": self.material,
                "method": self.method, "maps": [m.to_dict() for m in self.maps],
                "fingerprints": self.fingerprints}

    @classmethod
    def from_dict(cls, d: dict) -> "HeightMapSet":
        if d.get("format") != "lumacut-heightmaps/1":
            raise ValueError("Unbekanntes Höhenmesh-Format")
        return cls([HeightMap.from_dict(m) for m in d["maps"]], d.get("created", 0.0),
                   d.get("material", ""), d.get("fingerprints", {}), d.get("method", "bicubic"))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "HeightMapSet":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _patch(mosaic, rect: Rect, size: int):
    import cv2
    c0, r0 = mosaic.machine_to_pixel(rect.xmin, rect.ymin)
    c1, r1 = mosaic.machine_to_pixel(rect.xmax, rect.ymax)
    h, w = mosaic.image.shape[:2]
    c0, r0 = max(0, int(c0)), max(0, int(r0))
    c1, r1 = min(w, int(math.ceil(c1))), min(h, int(math.ceil(r1)))
    if c1 - c0 < 8 or r1 - r0 < 8:
        return None
    g = cv2.cvtColor(mosaic.image[r0:r1, c0:c1], cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (size, size), interpolation=cv2.INTER_AREA)
