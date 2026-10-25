"""Kamera-Kalibrierung für den Kachel-Scan bei fester Höhe.

Modell (Kamera fest am Laserkopf, Bild bei festem Z ``scan_z``):

    machine = head + offset + R(rotation) · diag(flip_x, flip_y) · (pixel − center) / px_per_mm

* ``head``   – Laserpunkt-Position der Maschine beim Aufnehmen
* ``offset`` – Bildmitte relativ zum Laserpunkt (mm)
* ``flip_y`` – +1, wenn die Bildzeile (nach unten) mit Maschinen +Y wächst

Linsenverzeichnung optional über OpenCV (``camera_matrix``, ``dist_coeffs``).
Die Werte stammen aus einer einmaligen Kalibrierung (z. B. Schachbrett für die
Linse, dann ein gelaserter Fadenkreuz-Test für Offset/Maßstab/Rotation).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

try:  # OpenCV ist Pflicht für Entzerrung/Stitching, nicht für Planung
    import cv2
except ImportError:  # pragma: no cover - nur ohne OpenCV
    cv2 = None


@dataclass
class CameraCalibration:
    image_width: int
    image_height: int
    px_per_mm: float                      # Maßstab bei scan_z
    scan_z: float = 40.0                  # feste Scanhöhe (Maschinen-Z, mm)
    offset_mm: tuple[float, float] = (0.0, 0.0)
    rotation_deg: float = 0.0
    flip_x: int = 1
    flip_y: int = 1
    crop_fraction: float = 0.04           # vignettierte Ränder verwerfen
    camera_matrix: Optional[list[list[float]]] = None
    dist_coeffs: Optional[list[float]] = None
    _maps: Optional[tuple] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError("Image size must be positive")
        if not (self.px_per_mm > 0 and math.isfinite(self.px_per_mm)):
            raise ValueError("px_per_mm must be positive")
        if self.flip_x not in (1, -1) or self.flip_y not in (1, -1):
            raise ValueError("flip_x/flip_y must be +1 or -1")
        if not (0 <= self.crop_fraction < 0.4):
            raise ValueError("crop_fraction must be in [0, 0.4)")
        self.offset_mm = (float(self.offset_mm[0]), float(self.offset_mm[1]))

    # ------------------------------------------------------------------
    @property
    def has_distortion(self) -> bool:
        return self.camera_matrix is not None and self.dist_coeffs is not None

    @property
    def crop_px(self) -> tuple[int, int]:
        return (int(round(self.image_width * self.crop_fraction)),
                int(round(self.image_height * self.crop_fraction)))

    @property
    def usable_fov_mm(self) -> tuple[float, float]:
        """Nutzbares Sichtfeld (nach Randbeschnitt), in Maschinenachsen."""
        cx, cy = self.crop_px
        w = (self.image_width - 2 * cx) / self.px_per_mm
        h = (self.image_height - 2 * cy) / self.px_per_mm
        a = math.radians(self.rotation_deg)
        # achsparalleles Rechteck, das sicher im gedrehten Sichtfeld liegt
        if abs(math.sin(a)) < 1e-9:
            return (w, h)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        # größtes achsparalleles Rechteck gleicher Proportion im gedrehten
        k = min(w / (w * c + h * s), h / (w * s + h * c))
        return (w * k, h * k)

    @property
    def mm_per_px(self) -> float:
        return 1.0 / self.px_per_mm

    def linear_matrix(self) -> np.ndarray:
        """2×2: Pixel-Versatz (u, v) → Maschinen-Versatz (mm)."""
        a = math.radians(self.rotation_deg)
        rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        return rot @ np.diag([self.flip_x, self.flip_y]) / self.px_per_mm

    def pixel_to_machine(self, u: float, v: float, head: tuple[float, float]) -> tuple[float, float]:
        cu, cv = (self.image_width - 1) / 2, (self.image_height - 1) / 2
        d = self.linear_matrix() @ np.array([u - cu, v - cv])
        return (head[0] + self.offset_mm[0] + d[0], head[1] + self.offset_mm[1] + d[1])

    def machine_to_pixel(self, x: float, y: float, head: tuple[float, float]) -> tuple[float, float]:
        cu, cv = (self.image_width - 1) / 2, (self.image_height - 1) / 2
        inv = np.linalg.inv(self.linear_matrix())
        d = inv @ np.array([x - head[0] - self.offset_mm[0], y - head[1] - self.offset_mm[1]])
        return (cu + d[0], cv + d[1])

    def head_for_view_center(self, x: float, y: float) -> tuple[float, float]:
        """Kopfposition, damit (x, y) in der Bildmitte liegt."""
        return (x - self.offset_mm[0], y - self.offset_mm[1])

    # ------------------------------------------------------------------
    def undistort(self, image: np.ndarray) -> np.ndarray:
        if not self.has_distortion:
            return image
        if cv2 is None:  # pragma: no cover
            raise RuntimeError("OpenCV (opencv-python-headless) required for undistortion")
        h, w = image.shape[:2]
        if (w, h) != (self.image_width, self.image_height):
            raise ValueError(f"Image size {w}x{h} does not match calibration "
                             f"{self.image_width}x{self.image_height}")
        if self._maps is None:
            k = np.array(self.camera_matrix, dtype=np.float64)
            d = np.array(self.dist_coeffs, dtype=np.float64)
            # gleiche Kameramatrix behalten -> Maßstab px_per_mm bleibt gültig
            self._maps = cv2.initUndistortRectifyMap(k, d, None, k, (w, h), cv2.CV_32FC1)
        return cv2.remap(image, self._maps[0], self._maps[1], cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_CONSTANT)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_maps", None)
        d["offset_mm"] = list(self.offset_mm)
        d["format"] = "lumacut-camera-calibration/1"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CameraCalibration":
        d = dict(d)
        d.pop("format", None)
        d.pop("_maps", None)
        d["offset_mm"] = tuple(d.get("offset_mm", (0.0, 0.0)))
        return cls(**d)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CameraCalibration":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
