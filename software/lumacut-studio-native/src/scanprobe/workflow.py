"""Gesamtablauf Scan -> Erkennen -> Proben -> Höhenmesh, Qt-frei.

Besser als xTool:
* vollflächiger Kachel-Scan statt eines verzerrten Einzel-Snapshots
* Objekte werden erkannt und **nur** diese Bereiche geprobt, je eigenes Mesh
* Bereichsvorschlag aus den Design-Boxen des Canvas
* Zeitabschätzung vor dem Start, Pause/Fortsetzen/Abbrechen, Fortschritt + ETA
* Wiederverwendung gespeicherter Meshes, wenn das Material nicht bewegt wurde
  (Bildvergleich + optional 3 Kontrollmessungen statt kompletter Abtastung)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional, Sequence

from .calibration import CameraCalibration
from .control import RunControl
from .detection import DetectedObject, detect_objects
from .geometry import Rect, MachineLimits, DEFAULT_LIMITS
from .heightmap import HeightMapSet
from .interfaces import MachineInterface, CameraInterface, ProbeInterface
from .probe_plan import (ProbeArea, ProbeSettings, ProbeJob, plan_probe_job,
                         areas_from_objects, areas_from_design_bounds)
from .probing import ProbeRunner, ProbeResult
from .stitch import Mosaic, stitch_mosaic
from .tile_scan import TileScanner, TilePlan, plan_tiles


@dataclass
class WorkflowResult:
    mosaic: Optional[Mosaic] = None
    objects: list[DetectedObject] = field(default_factory=list)
    areas: list[ProbeArea] = field(default_factory=list)
    job: Optional[ProbeJob] = None
    probe: Optional[ProbeResult] = None
    reused: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def maps(self) -> Optional[HeightMapSet]:
        return self.probe.maps if self.probe else None


class ScanProbeWorkflow:
    def __init__(self, machine: MachineInterface, camera: Optional[CameraInterface],
                 probe: Optional[ProbeInterface], calibration: CameraCalibration,
                 probe_settings: Optional[ProbeSettings] = None,
                 control: Optional[RunControl] = None, limits: MachineLimits = DEFAULT_LIMITS,
                 overlap: float = 0.25, mosaic_mm_per_px: Optional[float] = None,
                 settle_s: float = 0.15):
        self.machine = machine
        self.camera = camera
        self.probe = probe
        self.calibration = calibration
        self.settings = probe_settings or ProbeSettings()
        self.control = control or RunControl()
        self.limits = limits
        self.overlap = overlap
        self.mosaic_mm_per_px = mosaic_mm_per_px
        self.settle_s = settle_s

    # ---- Schritte einzeln (für die UI) ---------------------------------
    def plan_scan(self, bounds: Optional[Rect] = None) -> TilePlan:
        return plan_tiles(bounds or self.limits.work_rect, self.calibration, self.overlap, self.limits)

    def scan(self, bounds: Optional[Rect] = None, plan: Optional[TilePlan] = None) -> Mosaic:
        if self.camera is None:
            raise RuntimeError("Keine Kamera angebunden")
        plan = plan or self.plan_scan(bounds)
        tiles = TileScanner(self.machine, self.camera, self.calibration, self.control,
                            settle_s=self.settle_s).run(plan)
        return stitch_mosaic(tiles, self.calibration, plan.bounds, self.mosaic_mm_per_px,
                             control=self.control)

    def detect(self, mosaic: Mosaic, background: Optional[Mosaic] = None, **kw) -> list[DetectedObject]:
        return detect_objects(mosaic, background, **kw)

    def suggest_areas(self, objects: Sequence[DetectedObject],
                      design_bounds: Optional[Sequence[Rect]] = None,
                      include_unused_objects: bool = False) -> tuple[list[ProbeArea], list[str]]:
        """Ohne Design: alle erkannten Objekte. Mit Design: nur Objekte unter dem Design."""
        if not design_bounds:
            return areas_from_objects(objects), []
        return areas_from_design_bounds(design_bounds, objects,
                                        include_unused_objects=include_unused_objects)

    def plan_probe(self, areas: Sequence[ProbeArea], start=(0.0, 0.0)) -> ProbeJob:
        return plan_probe_job(areas, self.settings, start, self.limits)

    def probe_areas(self, job: ProbeJob, start=(0.0, 0.0), mosaic: Optional[Mosaic] = None) -> ProbeResult:
        if self.probe is None:
            raise RuntimeError("Kein Taster angebunden")
        res = ProbeRunner(self.probe, self.control).run(job, start)
        if mosaic is not None:
            res.maps.add_fingerprints(mosaic)
        self.machine.move_to(None, None, self.settings.safe_z, None)
        return res

    def estimate(self, scan_bounds: Optional[Rect] = None, job: Optional[ProbeJob] = None) -> dict:
        """Geschätzte Dauer in Sekunden je Phase (vor dem Start anzeigen)."""
        out = {"scan_s": self.plan_scan(scan_bounds).estimate_seconds()}
        if job is not None:
            out["probe_s"] = job.estimate_seconds()
            out["probe_points"] = len(job.points)
        out["total_s"] = sum(v for k, v in out.items() if k.endswith("_s"))
        return out

    # ---- Wiederverwendung ---------------------------------------------
    def try_reuse(self, saved: HeightMapSet, mosaic: Optional[Mosaic] = None,
                  spot_checks: int = 3, tolerance_mm: float = 0.15) -> tuple[bool, list[str]]:
        """Gespeichertes Mesh wiederverwenden, wenn das Material nicht bewegt wurde.

        1. Bildvergleich je Bereich (falls Mosaik + Fingerabdrücke vorhanden)
        2. ``spot_checks`` Kontrollmessungen je Bereich (Mitte zuerst)
        """
        notes: list[str] = []
        if mosaic is not None and saved.fingerprints:
            for aid, r in saved.check_material_unchanged(mosaic).items():
                if not r["ok"]:
                    notes.append(f"{aid}: Material bewegt/verändert (Versatz {r['shift_mm']:.2f} mm, "
                                 f"Ähnlichkeit {r['similarity']:.2f})")
            if notes:
                return False, notes
        if spot_checks > 0:
            if self.probe is None:
                return False, ["Kein Taster für Kontrollmessung"]
            s = self.settings
            for m in saved.maps:
                pts = _spot_points(m, spot_checks)
                for x, y in pts:
                    self.control.checkpoint()
                    z = self.probe.probe_z(x, y, safe_z=s.safe_z, feed=s.probe_feed, max_depth=s.max_depth)
                    exp = m.z_at(x, y)
                    if z is None or abs(z - exp) > tolerance_mm:
                        notes.append(f"{m.area_id}: Kontrollmessung X{x:.1f} Y{y:.1f} "
                                     f"{'ohne Kontakt' if z is None else f'{z:.3f}'} statt {exp:.3f} mm")
                        return False, notes
            notes.append(f"Höhenmesh wiederverwendet ({sum(min(spot_checks, m.measured_count) for m in saved.maps)} Kontrollmessungen ok)")
        return True, notes

    # ---- alles in einem ----------------------------------------------
    def run(self, scan_bounds: Optional[Rect] = None, design_bounds: Optional[Sequence[Rect]] = None,
            background: Optional[Mosaic] = None, saved: Optional[HeightMapSet] = None,
            manual_areas: Sequence[ProbeArea] = (), start=(0.0, 0.0)) -> WorkflowResult:
        res = WorkflowResult()
        res.mosaic = self.scan(scan_bounds)
        if saved is not None:
            ok, notes = self.try_reuse(saved, res.mosaic)
            res.notes += notes
            if ok:
                res.reused = True
                res.probe = ProbeResult(saved)
                return res
        res.objects = self.detect(res.mosaic, background)
        areas, notes = self.suggest_areas(res.objects, design_bounds)
        res.areas = list(areas) + list(manual_areas)
        res.notes += notes
        if not res.areas:
            res.notes.append("Keine Werkstücke erkannt – Bereiche bitte manuell markieren.")
            return res
        res.job = self.plan_probe(res.areas, start)
        res.notes += res.job.warnings
        res.probe = self.probe_areas(res.job, start, res.mosaic)
        return res


def _spot_points(m, n: int) -> list[tuple[float, float]]:
    import numpy as np
    v = m.valid
    X, Y = np.meshgrid(m.xs, m.ys)
    pts = list(zip(X[v].tolist(), Y[v].tolist()))
    if not pts:
        return []
    cx, cy = m.polygon.centroid
    pts.sort(key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    chosen = [pts[0]]
    while len(chosen) < min(n, len(pts)):  # weit auseinander liegende Punkte
        chosen.append(max(pts, key=lambda p: min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in chosen)))
    return chosen
