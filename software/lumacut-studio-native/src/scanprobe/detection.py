"""Automatische Erkennung aufgelegter Werkstücke im Scan-Mosaik.

Zwei Wege, kombinierbar:
* **Leerbett-Referenz** (empfohlen): Differenz zu einem früheren Scan des
  leeren Betts – robust auch bei dunklem Material auf dunklem Wabenbett.
* **Ohne Referenz**: Farb-/Helligkeitsabstand zum geschätzten Bett-Hintergrund
  (Median) + Otsu, Wabenstruktur wird per Morphologie entfernt.

Jedes Objekt wird klassifiziert (``rectangle``, ``circle``, ``polygon``) und
in Maschinenkoordinaten (mm) zurückgegeben.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional

import numpy as np
import cv2

from .geometry import Polygon, Rect, circle_polygon
from .stitch import Mosaic


@dataclass
class DetectedObject:
    id: str
    kind: str                         # "rectangle" | "circle" | "polygon"
    polygon: Polygon                  # Umriss in Maschinen-mm
    bounds: Rect
    center: tuple[float, float]
    area_mm2: float
    confidence: float                 # 0..1 (Formtreue)
    rotation_deg: float = 0.0         # Rechtecke
    radius_mm: Optional[float] = None  # Kreise
    size_mm: Optional[tuple[float, float]] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "polygon": self.polygon.to_list(),
                "bounds": self.bounds.to_list(), "center": list(self.center),
                "area_mm2": self.area_mm2, "confidence": self.confidence,
                "rotation_deg": self.rotation_deg, "radius_mm": self.radius_mm,
                "size_mm": list(self.size_mm) if self.size_mm else None}


def foreground_mask(mosaic: Mosaic, background: Optional[Mosaic] = None,
                    texture_mm: float = 4.0, threshold: Optional[float] = None) -> np.ndarray:
    """Binärmaske (uint8 0/255) der Werkstücke im Mosaik."""
    img = mosaic.image
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    # Textur (Waben, Holzmaserung) glätten, Kanten bleiben über Median erhalten
    k = max(3, int(round(texture_mm / mosaic.mm_per_px)) | 1)
    k = min(k, 31)
    if background is not None:
        if background.image.shape != img.shape or abs(background.mm_per_px - mosaic.mm_per_px) > 1e-9:
            raise ValueError("Leerbett-Referenz muss gleiche Größe und Auflösung haben")
        blab = cv2.cvtColor(background.image, cv2.COLOR_BGR2LAB).astype(np.float32)
        diff = np.linalg.norm(lab - blab, axis=2)
    else:
        bg = np.median(lab[mosaic.coverage], axis=0) if mosaic.coverage.any() else np.zeros(3)
        diff = np.linalg.norm(lab - bg[None, None, :], axis=2)
    diff = cv2.medianBlur(np.clip(diff, 0, 255).astype(np.uint8), k)
    diff[~mosaic.coverage] = 0
    if threshold is None:
        t, _ = cv2.threshold(diff[mosaic.coverage].reshape(-1, 1), 0, 255,
                             cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        threshold = max(float(t), 18.0)  # Mindestkontrast gegen Rauschen
    mask = (diff > threshold).astype(np.uint8) * 255
    kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kk)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kk)
    return mask


def detect_objects(mosaic: Mosaic, background: Optional[Mosaic] = None,
                   min_area_mm2: float = 150.0, min_size_mm: float = 8.0,
                   texture_mm: float = 4.0, threshold: Optional[float] = None,
                   fill_holes: bool = True) -> list[DetectedObject]:
    """Werkstücke im Mosaik finden. Ergebnis sortiert nach Fläche (groß zuerst)."""
    mask = foreground_mask(mosaic, background, texture_mm, threshold)
    mode = cv2.RETR_EXTERNAL if fill_holes else cv2.RETR_CCOMP
    contours, _ = cv2.findContours(mask, mode, cv2.CHAIN_APPROX_NONE)
    s = mosaic.mm_per_px
    out: list[DetectedObject] = []
    for c in contours:
        area_px = cv2.contourArea(c)
        area = area_px * s * s
        if area < min_area_mm2:
            continue
        (rcx, rcy), (rw, rh), ang = cv2.minAreaRect(c)
        if min(rw, rh) * s < min_size_mm:
            continue
        perim = cv2.arcLength(c, True)
        circularity = 4 * math.pi * area_px / (perim * perim) if perim > 0 else 0
        rectangularity = area_px / (rw * rh) if rw * rh > 0 else 0
        (ccx, ccy), cr = cv2.minEnclosingCircle(c)
        circle_fill = area_px / (math.pi * cr * cr) if cr > 0 else 0
        to_mm = lambda px, py: mosaic.pixel_to_machine(px, py)
        if circle_fill > 0.86 and circularity > 0.82 and min(rw, rh) / max(rw, rh) > 0.9:
            # Kreis: Mittelpunkt aus Momenten, Radius aus Fläche (robuster als Hüllkreis)
            m = cv2.moments(c)
            cx, cy = to_mm(m["m10"] / m["m00"], m["m01"] / m["m00"])
            r = math.sqrt(area_px / math.pi) * s
            poly = circle_polygon(cx, cy, r, 64)
            kind, conf, rot, size, radius = "circle", min(1.0, circle_fill), 0.0, (2 * r, 2 * r), r
        elif rectangularity > 0.9:
            box = cv2.boxPoints(((rcx, rcy), (rw, rh), ang))
            poly = Polygon(tuple(to_mm(px, py) for px, py in box))
            cx, cy = to_mm(rcx, rcy)
            w_mm, h_mm = rw * s, rh * s
            rot = float(ang)
            if w_mm < h_mm:
                w_mm, h_mm, rot = h_mm, w_mm, rot + 90.0
            rot = ((rot + 90) % 180) - 90
            kind, conf, size, radius = "rectangle", min(1.0, rectangularity), (w_mm, h_mm), None
        else:
            approx = cv2.approxPolyDP(c, max(1.0, 0.5 / s), True)  # 0,5 mm Toleranz
            pts = approx.reshape(-1, 2)
            if len(pts) < 3:
                continue
            poly = Polygon(tuple(to_mm(px, py) for px, py in pts))
            cx, cy = poly.centroid
            kind, conf, rot, size, radius = "polygon", float(rectangularity), 0.0, (rw * s, rh * s), None
        out.append(DetectedObject("", kind, poly, poly.bounds, (cx, cy), area, conf, rot, radius, size))
    out.sort(key=lambda o: -o.area_mm2)
    for i, o in enumerate(out, 1):
        o.id = f"obj{i}"
    return out
