"""Ausführung der Bereichs-Abtastung mit Fehlerbehandlung.

* Wiederholung bei Fehlmessung, leicht versetzt (Loch, Span, Staub)
* Ausreißer-Prüfung gegen den Median der Nachbarn, einmal nachmessen
* Adaptive Nachverdichtung: Zellmitte messen, wenn die bilineare Vorhersage
  um mehr als ``adaptive_threshold_mm`` daneben liegt -> Zelle verfeinern
* Kurzer Z-Hub innerhalb eines Bereichs (höchster Messwert + ``hop_mm``),
  volle Rückzughöhe nur zwischen Bereichen
* Pause / Fortsetzen / Abbrechen zwischen zwei Messungen, Fortschritt + ETA
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Optional

import numpy as np

from .control import RunControl, Progress, EtaEstimator
from .heightmap import (HeightMap, HeightMapSet, MEASURED, RETRIED, INTERPOLATED, FAILED,
                        OUTLIER, NOT_PROBED, SUBSTITUTED)
from .interfaces import ProbeInterface
from .probe_plan import ProbeJob, ProbeSettings, AreaGrid, clamp_to, substitution_note


@dataclass
class ProbeResult:
    maps: HeightMapSet
    probes: int = 0
    failures: list[tuple[str, float, float]] = field(default_factory=list)
    outliers: list[tuple[str, float, float, float]] = field(default_factory=list)
    adaptive_points: int = 0
    #: Ersatzpunkte (§2.4): (Bereich, x, y, gemessen_x, gemessen_y)
    substituted: list[tuple[str, float, float, float, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(m.measured_count > 0 for m in self.maps.maps)


def _reachable(grid: AreaGrid, x: float, y: float) -> bool:
    if grid.reach is None:
        return True
    return clamp_to(grid.reach, x, y) == (x, y)


class ProbeRunner:
    def __init__(self, probe: ProbeInterface, control: Optional[RunControl] = None):
        self.probe = probe
        self.control = control or RunControl()
        self._count = 0

    # ------------------------------------------------------------------
    def run(self, job: ProbeJob, start=(0.0, 0.0)) -> ProbeResult:
        s = job.settings
        t0 = time.monotonic()
        total = len(job.points)
        est = job.estimate_seconds(start) / max(1, total)
        self._eta = EtaEstimator(total, est)
        self._total = total
        self._count = 0
        result = ProbeResult(HeightMapSet([]))
        for grid in job.grids:
            if not grid.points:
                result.log.append(f"{grid.area.id}: übersprungen (keine Punkte)")
                continue
            hm = HeightMap.empty(grid.area.id, grid.area.polygon, grid.xs, grid.ys, grid.area.kind)
            hm.edge_tolerance_mm = max(s.margin_mm + 2.0, 3.0)
            self._top = None  # höchste Oberfläche im Bereich (für Z-Hub)
            for p in grid.points:
                z, st = self._measure(grid, p.x, p.y, s, result)
                hm.set(p.i, p.j, z, st)
            self._check_outliers(grid, hm, s, result)
            if s.adaptive and len(grid.xs) >= 2 and len(grid.ys) >= 2:
                hm = self._refine(grid, hm, s, result)
            if hm.measured_count == 0:
                result.log.append(f"{grid.area.id}: keine gültige Messung – Bereich nicht kompensierbar")
            result.maps.maps.append(hm)
        note = substitution_note(job.grids)
        if note:
            result.warnings.append(note)
            result.log.append(note)
        # zurück auf Rückzughöhe
        result.duration_s = time.monotonic() - t0
        return result

    # ------------------------------------------------------------------
    def _z_travel(self, s: ProbeSettings) -> float:
        if self._top is None:
            return s.safe_z
        return min(s.safe_z, self._top + s.hop_mm)

    def _measure(self, grid: AreaGrid, x: float, y: float, s: ProbeSettings,
                 result: ProbeResult, count: bool = True):
        r = s.retry_offset_mm
        offsets = [(0.0, 0.0), (r, 0.0), (0.0, r), (-r, 0.0), (0.0, -r)][: s.retries + 1]
        poly = grid.area.polygon
        attempt = 0
        # Nicht erreichbar -> am nächsten erreichbaren Punkt messen (§2.4)
        bx, by = clamp_to(grid.reach, x, y) if grid.reach is not None else (x, y)
        subst = abs(bx - x) > 1e-6 or abs(by - y) > 1e-6
        for dx, dy in offsets:
            px, py = bx + dx, by + dy
            if grid.reach is not None:
                px, py = clamp_to(grid.reach, px, py)
            if attempt and (subst or not poly.contains_with_margin(px, py, s.margin_mm / 2)):
                continue
            self.control.checkpoint()
            z = self.probe.probe_z(px, py, safe_z=self._z_travel(s), feed=s.probe_feed,
                                   max_depth=s.max_depth)
            result.probes += 1
            attempt += 1
            if z is not None and math.isfinite(z) and s.max_depth < z < s.safe_z:
                self._top = z if self._top is None else max(self._top, z)
                self._progress(grid, count)
                if subst:
                    result.substituted.append((grid.area.id, x, y, bx, by))
                    result.log.append(f"{grid.area.id}: X{x:.2f} Y{y:.2f} nicht erreichbar – "
                                      f"Ersatzmessung bei X{bx:.2f} Y{by:.2f}")
                    return z, SUBSTITUTED
                return z, (MEASURED if attempt == 1 else RETRIED)
        result.failures.append((grid.area.id, x, y))
        result.log.append(f"{grid.area.id}: kein Kontakt bei X{x:.2f} Y{y:.2f} nach {attempt} Versuch(en)")
        self._progress(grid, count)
        return None, FAILED

    def _progress(self, grid: AreaGrid, count: bool):
        if count:
            self._count += 1
        self.control.report(Progress("probe", self._count, self._total,
                                     f"{grid.area.id}: Punkt {self._count}/{self._total}",
                                     self._eta.eta(self._count), {"area_id": grid.area.id}))

    def _check_outliers(self, grid: AreaGrid, hm: HeightMap, s: ProbeSettings, result: ProbeResult):
        ny, nx = hm.z.shape
        for j in range(ny):
            for i in range(nx):
                if not hm.valid[j, i]:
                    continue
                nb = [hm.z[jj, ii] for jj in range(max(0, j - 1), min(ny, j + 2))
                      for ii in range(max(0, i - 1), min(nx, i + 2))
                      if (ii, jj) != (i, j) and hm.valid[jj, ii]]
                if len(nb) < 3:
                    continue
                med = float(np.median(nb))
                old = float(hm.z[j, i])
                if abs(old - med) <= s.outlier_mm:
                    continue
                x, y = hm.xs[i], hm.ys[j]
                z, st = self._measure(grid, x, y, s, result, count=False)
                if z is not None and abs(z - med) <= s.outlier_mm:
                    hm.set(i, j, z, RETRIED)
                    result.outliers.append((grid.area.id, x, y, old))
                    result.log.append(f"{grid.area.id}: Ausreißer bei X{x:.2f} Y{y:.2f} ({old:.2f} mm) "
                                      f"nachgemessen -> {z:.3f} mm")
                elif z is not None and abs(z - old) <= 0.1:
                    pass  # reproduzierbar -> echte Stufe/Verzug, behalten
                else:
                    hm.set(i, j, None, OUTLIER)
                    result.outliers.append((grid.area.id, x, y, old))
                    result.log.append(f"{grid.area.id}: Ausreißer bei X{x:.2f} Y{y:.2f} ({old:.2f} mm) verworfen")

    def _refine(self, grid: AreaGrid, hm: HeightMap, s: ProbeSettings, result: ProbeResult) -> HeightMap:
        ny, nx = hm.z.shape
        v = hm.valid
        cells = []
        for j in range(ny - 1):
            for i in range(nx - 1):
                if v[j:j + 2, i:i + 2].all():
                    c = hm.z[j:j + 2, i:i + 2]
                    cells.append((float(c.max() - c.min()), i, j))
        cells.sort(reverse=True)
        budget = s.adaptive_max_points
        centers: dict[tuple[int, int], float] = {}
        refine: list[tuple[int, int]] = []
        poly = grid.area.polygon
        for rng, i, j in cells:
            if budget <= 0 or rng < s.adaptive_threshold_mm:
                break
            cx, cy = (hm.xs[i] + hm.xs[i + 1]) / 2, (hm.ys[j] + hm.ys[j + 1]) / 2
            if not poly.contains_with_margin(cx, cy, s.margin_mm) or not _reachable(grid, cx, cy):
                continue   # Verfeinern nur, wo der Taster wirklich hinkommt
            z, st = self._measure(grid, cx, cy, s, result, count=False)
            budget -= 1
            result.adaptive_points += 1
            if z is None:
                continue
            centers[(i, j)] = z
            if abs(z - hm.z_at(cx, cy, "bicubic")) > s.adaptive_threshold_mm:
                refine.append((i, j))
        if not refine:
            if centers:
                result.log.append(f"{hm.area_id}: {len(centers)} Zellmitte(n) geprüft – Mesh bestätigt")
            return hm
        # feines Raster mit halbem Abstand
        xs2 = np.empty(2 * nx - 1)
        xs2[0::2] = hm.xs
        xs2[1::2] = (hm.xs[:-1] + hm.xs[1:]) / 2
        ys2 = np.empty(2 * ny - 1)
        ys2[0::2] = hm.ys
        ys2[1::2] = (hm.ys[:-1] + hm.ys[1:]) / 2
        fine = HeightMap.empty(hm.area_id, hm.polygon, xs2, ys2, hm.kind)
        fine.edge_tolerance_mm = hm.edge_tolerance_mm
        fine.z[0::2, 0::2] = hm.z
        fine.status[0::2, 0::2] = hm.status
        coarse = hm.z
        for (i, j), z in centers.items():
            fine.z[2 * j + 1, 2 * i + 1] = z
            fine.status[2 * j + 1, 2 * i + 1] = MEASURED
        for (i, j) in refine:
            for (fi, fj) in ((2 * i + 1, 2 * j), (2 * i + 1, 2 * j + 2), (2 * i, 2 * j + 1), (2 * i + 2, 2 * j + 1)):
                if fine.status[fj, fi] in (MEASURED, RETRIED, SUBSTITUTED) or budget <= 0:
                    continue
                x, y = xs2[fi], ys2[fj]
                if not poly.contains_with_margin(x, y, s.margin_mm) or not _reachable(grid, x, y):
                    continue
                z, st = self._measure(grid, x, y, s, result, count=False)
                budget -= 1
                result.adaptive_points += 1
                if z is not None:
                    fine.z[fj, fi] = z
                    fine.status[fj, fi] = st
        # übrige neue Knoten: bikubisch aus dem groben Raster + Korrektur aus den
        # Residuen der neuen Messungen in der Nähe (glatt statt Stufen)
        new_meas = [(xs2[fi], ys2[fj], float(fine.z[fj, fi]) - hm.z_at(xs2[fi], ys2[fj], "bicubic"))
                    for fj in range(len(ys2)) for fi in range(len(xs2))
                    if (fi % 2 or fj % 2) and fine.status[fj, fi] in (MEASURED, RETRIED, SUBSTITUTED)]
        reach = float(max(np.diff(hm.xs).max() if nx > 1 else 0, np.diff(hm.ys).max() if ny > 1 else 0))
        for fj in range(len(ys2)):
            for fi in range(len(xs2)):
                if fine.status[fj, fi] != NOT_PROBED or (fi % 2 == 0 and fj % 2 == 0):
                    continue
                i0, j0 = fi // 2, fj // 2
                i1, j1 = min(i0 + (fi % 2), nx - 1), min(j0 + (fj % 2), ny - 1)
                if not v[[j0, j0, j1, j1], [i0, i1, i0, i1]].all():
                    continue
                x, y = xs2[fi], ys2[fj]
                corr, wsum = 0.0, 0.0
                for mx, my, r in new_meas:
                    d = math.hypot(mx - x, my - y)
                    if d < reach:
                        w = (1 - d / reach) ** 2 / max(d, 1e-6)
                        corr += w * r
                        wsum += w
                # Korrektur zur Mitte hin gewichten, an groben Knoten (gemessen) -> 0
                fine.z[fj, fi] = hm.z_at(x, y, "bicubic") + (corr / wsum * min(1.0, wsum * reach / 4) if wsum else 0.0)
                fine.status[fj, fi] = INTERPOLATED
        fine._filled = None
        result.log.append(f"{hm.area_id}: {len(centers)} Zellmitte(n) geprüft, {len(refine)} Zelle(n) verfeinert")
        return fine
