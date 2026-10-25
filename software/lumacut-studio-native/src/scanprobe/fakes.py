"""Simulierte Maschine, Kamera und Taster für Tests und Offline-Demo.

Keine Hardware nötig. ``SyntheticBed`` beschreibt eine Szene in
Maschinenkoordinaten (Bild + Höhenfunktion), ``FakeCamera`` rendert daraus
mit derselben Kalibrierung, die der Scanner verwendet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from typing import Callable, Optional

import numpy as np
import cv2

from .calibration import CameraCalibration
from .geometry import MachineLimits, DEFAULT_LIMITS


@dataclass
class SyntheticBed:
    """Draufsicht auf das Bett: ``image`` deckt Maschinen-Rect ab (0,0)… ."""
    image: np.ndarray
    mm_per_px: float
    surface: Callable[[float, float], Optional[float]]   # Z der Oberfläche oder None

    @classmethod
    def with_objects(cls, size_mm=(390.0, 370.0), mm_per_px=0.25, seed=1,
                     objects: Optional[list[dict]] = None, bed_z: float = 0.0) -> "SyntheticBed":
        """Wabenbett-ähnlicher dunkler Hintergrund + helle Werkstücke.

        ``objects``: dicts ``{"kind": "rect", "rect": (x0,y0,x1,y1), "z": f(x,y)|float}``
        oder ``{"kind": "circle", "center": (x,y), "r": r, "z": ...}``.
        """
        rng = np.random.default_rng(seed)
        W, H = int(size_mm[0] / mm_per_px), int(size_mm[1] / mm_per_px)
        img = np.full((H, W, 3), 45, np.uint8)
        # Wabenmuster als Textur
        pitch = max(4, int(6 / mm_per_px))
        for yy in range(0, H, pitch):
            off = (pitch // 2) if (yy // pitch) % 2 else 0
            for xx in range(off, W, pitch):
                cv2.circle(img, (xx, yy), max(1, pitch // 3), (30, 30, 30), -1)
        img = cv2.add(img, rng.integers(0, 8, img.shape, dtype=np.uint8))
        objects = objects or []
        for i, o in enumerate(objects):
            color = o.get("color", (170 + 20 * (i % 3), 190, 210 - 15 * (i % 3)))
            if o["kind"] == "rect":
                x0, y0, x1, y1 = o["rect"]
                cv2.rectangle(img, (int(x0 / mm_per_px), int(y0 / mm_per_px)),
                              (int(x1 / mm_per_px), int(y1 / mm_per_px)), color, -1)
            elif o["kind"] == "circle":
                cx, cy = o["center"]
                cv2.circle(img, (int(cx / mm_per_px), int(cy / mm_per_px)), int(o["r"] / mm_per_px), color, -1)
            # Holzmaserung / Text als Struktur für die Phasenkorrelation
            tex = rng.integers(0, 40, img.shape[:2], dtype=np.uint8)
            tex = cv2.GaussianBlur(tex, (0, 0), 2)
            mask = np.zeros(img.shape[:2], np.uint8)
            if o["kind"] == "rect":
                x0, y0, x1, y1 = o["rect"]
                cv2.rectangle(mask, (int(x0 / mm_per_px), int(y0 / mm_per_px)),
                              (int(x1 / mm_per_px), int(y1 / mm_per_px)), 255, -1)
            else:
                cx, cy = o["center"]
                cv2.circle(mask, (int(cx / mm_per_px), int(cy / mm_per_px)), int(o["r"] / mm_per_px), 255, -1)
            for c in range(3):
                ch = img[:, :, c]
                ch[mask > 0] = np.clip(ch[mask > 0].astype(int) - tex[mask > 0], 0, 255)

        def surface(x: float, y: float) -> Optional[float]:
            for o in reversed(objects):
                inside = False
                if o["kind"] == "rect":
                    x0, y0, x1, y1 = o["rect"]
                    inside = x0 <= x <= x1 and y0 <= y <= y1
                else:
                    cx, cy = o["center"]
                    inside = math.hypot(x - cx, y - cy) <= o["r"]
                if inside:
                    z = o.get("z", 3.0)
                    return float(z(x, y) if callable(z) else z)
            return bed_z
        return cls(img, mm_per_px, surface)


class FakeMachine:
    """Zeichnet Fahrten auf, simuliert Taster mit Fehlern."""

    def __init__(self, bed: Optional[SyntheticBed] = None, limits: MachineLimits = DEFAULT_LIMITS,
                 position_error_mm: float = 0.0, probe_fail_rate: float = 0.0,
                 probe_noise_mm: float = 0.0, fail_points: Optional[set] = None, seed: int = 0):
        self.bed = bed
        self.limits = limits
        self.x = self.y = 0.0
        self.z = 20.0
        self.true_x = self.true_y = 0.0
        self.position_error_mm = position_error_mm
        self.probe_fail_rate = probe_fail_rate
        self.probe_noise_mm = probe_noise_mm
        self.fail_points = fail_points or set()
        self.moves: list[tuple] = []
        self.probes: list[tuple] = []
        self.travel_mm = 0.0
        self._rng = random.Random(seed)

    def move_to(self, x, y, z=None, feed=None):
        nx = self.x if x is None else float(x)
        ny = self.y if y is None else float(y)
        if not self.limits.reachable(nx, ny):
            raise ValueError(f"Ziel außerhalb des Fahrbereichs: {nx:.2f}/{ny:.2f}")
        self.travel_mm += math.hypot(nx - self.x, ny - self.y)
        self.x, self.y = nx, ny
        if z is not None:
            self.z = float(z)
        e = self.position_error_mm
        self.true_x = nx + (self._rng.uniform(-e, e) if e else 0.0)
        self.true_y = ny + (self._rng.uniform(-e, e) if e else 0.0)
        self.moves.append((nx, ny, self.z, feed))

    def wait_idle(self):
        pass

    def probe_z(self, x, y, *, safe_z, feed, max_depth):
        self.move_to(x, y, safe_z)
        key = (round(x, 3), round(y, 3))
        self.probes.append((x, y))
        if key in self.fail_points:
            return None
        if self.probe_fail_rate and self._rng.random() < self.probe_fail_rate:
            return None
        z = self.bed.surface(x, y) if self.bed else 0.0
        if z is None or z < max_depth:
            return None
        if self.probe_noise_mm:
            z += self._rng.gauss(0, self.probe_noise_mm)
        return z


class FakeCamera:
    """Rendert das Kamerabild für die aktuelle (wahre) Kopfposition."""

    def __init__(self, machine: FakeMachine, bed: SyntheticBed, calibration: CameraCalibration,
                 distort: bool = False, noise: float = 0.0, seed: int = 0):
        self.machine = machine
        self.bed = bed
        self.cal = calibration
        self.noise = noise
        self._rng = np.random.default_rng(seed)
        w, h = calibration.image_width, calibration.image_height
        u, v = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        if distort and calibration.has_distortion:
            # Für jedes verzerrte Pixel das ideale Pixel bestimmen
            k = np.array(calibration.camera_matrix, np.float64)
            d = np.array(calibration.dist_coeffs, np.float64)
            pts = np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2).astype(np.float64)
            und = cv2.undistortPoints(pts, k, d, P=k).reshape(h, w, 2)
            u, v = und[..., 0].astype(np.float32), und[..., 1].astype(np.float32)
        self._u, self._v = u, v
        self.captures = 0

    def capture(self) -> np.ndarray:
        cal = self.cal
        L = cal.linear_matrix()
        cu, cv_ = (cal.image_width - 1) / 2, (cal.image_height - 1) / 2
        hx, hy = self.machine.true_x, self.machine.true_y
        du, dv = self._u - cu, self._v - cv_
        mx = hx + cal.offset_mm[0] + L[0, 0] * du + L[0, 1] * dv
        my = hy + cal.offset_mm[1] + L[1, 0] * du + L[1, 1] * dv
        s = self.bed.mm_per_px
        mapx = (mx / s - 0.5).astype(np.float32)
        mapy = (my / s - 0.5).astype(np.float32)
        img = cv2.remap(self.bed.image, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=(20, 20, 20))
        if self.noise:
            img = np.clip(img + self._rng.normal(0, self.noise, img.shape), 0, 255).astype(np.uint8)
        self.captures += 1
        return img
