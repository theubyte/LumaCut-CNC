"""Ein-Klick-Auftrag (Qt-frei): Referenzfahrt → Probing → Fokus → Job → Parken.

Anforderungen 2026-10-26 §1: Höhenmesh und Fokuskorrektur sind **immer** Teil
des Auftrags, es gibt keine Auswahl „mit/ohne Heightmap“ mehr. Diese
Zustandsmaschine ruft die Maschine nur über die kleine Schnittstelle
:class:`MachinePort` auf (Machine-Agent: ``machine.client.LumaCutClient``,
siehe :class:`ClientMachinePort`) und das Proben über
:class:`scanprobe.workflow.ScanProbeWorkflow`. Sie läuft synchron in einem
Hintergrund-Thread; Pause/Abbrechen kommen über :class:`RunControl`.

Jede Zustandsänderung geht als JSON-taugliches ``dict`` an ``on_event``
(Vertrag in ``docs/SCAN_PROBE.md``, auch für eine spätere Android-App).

Ablauf
  1. ``referenzieren``: ``home()`` (Pi: XY zuerst, dann Z, Rückzug).
  2. ``probing``: Bereiche aus der Brennstrecke des Auftrags (plus erkannte
     Werkstücke aus einem optionalen Kamera-Scan). Ein vorhandenes, frisches
     Mesh, das den Auftrag abdeckt, wird nach Bildvergleich und 3
     Kontrollmessungen je Bereich wiederverwendet; sonst grobes Raster
     (``FAST_PROBE``) mit adaptiver Verfeinerung.
  3. ``fokus``: G30 am niedrigsten gemessenen Punkt. Damit liegt die Pi-Sperre
     („letztes G30 + 2 mm“) unter allen Fokushöhen – die frühere Warnung wird
     automatisch behandelt. Danach Fokuskorrektur mit allen Prüfungen
     (:func:`scanprobe.focus_export.compensate_for_export`); Fehler (Bögen,
     absolute Z-Wörter, bewegtes Material, Pi-Sperre) stoppen vor dem Lasern.
  4. ``job``: Hochladen, Starten, Fortschritt aus ``/api/status``.
  5. ``parken``: der Pi parkt am Auftragsende selbst (``park_safezone``);
     nach einem Fehler/Abbruch *vor* dem Lasern ruft der Ablauf ``park()``.

Pi-Ablauf: Meldet der Pi in ``/api/status`` das Merkmal ``autorun_mesh``
(Vertrag ``docs/ZUSAMMENARBEIT_CLAUDE_GROK.md`` §4, Pi-Teil von Claude), macht
der Pi Referenzfahrt, Abtasten und Höhenkorrektur selbst. Dann lädt der Ablauf
nur den unkorrigierten Auftrag hoch, startet ``op=autorun`` und spiegelt
``job.state``/``job.probe`` in dieselben Zustände. Ohne das Merkmal (heutiger
Pi) misst Studio das Mesh selbst und schickt fokuskorrigierten G-Code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
import time
from typing import Any, Callable, Optional, Protocol, Sequence

import numpy as np

from .compensation import _WORD
from .control import Cancelled, Progress, RunControl
from .focus_export import (MAX_AGE_H, FocusExport, compensate_for_export, job_coverage,
                           precheck_gcode)
from .geometry import Rect
from .heightmap import HeightMapSet
from .probe_plan import ProbeArea, ProbeSettings, areas_from_design_bounds
from .probing import ProbeResult

#: Zustände in Ablaufreihenfolge, dann Endzustände.
STEPS = ("referenzieren", "probing", "fokus", "job", "parken")
FINAL_STATES = ("fertig", "fehler", "abgebrochen")
STATES = ("bereit",) + STEPS + FINAL_STATES
STATE_LABELS = {
    "bereit": "Bereit",
    "referenzieren": "Referenzfahrt",
    "probing": "Höhenmesh messen",
    "fokus": "Fokus einstellen",
    "job": "Lasern",
    "parken": "Parken",
    "fertig": "Fertig",
    "fehler": "Fehler",
    "abgebrochen": "Abgebrochen",
}
#: Fehlercodes im Ereignis ``error.code`` (stabil für Clients).
ERROR_CODES = {
    "not_ready": "Maschine nicht bereit (Verbindung, Notstopp, laufender Auftrag)",
    "invalid_job": "Auftrag ungeeignet (keine Brennstrecke, Bögen, absolute Z-Wörter)",
    "homing_failed": "Referenzfahrt fehlgeschlagen",
    "probe_failed": "Höhenmesh konnte nicht gemessen werden",
    "focus_failed": "Fokus/Fokuskorrektur nicht möglich",
    "upload_failed": "Hochladen/Starten abgelehnt",
    "job_failed": "Auftrag auf dem Pi mit Fehler beendet",
    "emergency": "Notstopp aktiv",
    "connection_lost": "Verbindung zum Pi verloren",
    "cancelled": "Vom Nutzer abgebrochen",
}

#: Schnelles Probing: grobes Raster, Krümmung wird adaptiv nachverdichtet.
FAST_PROBE = ProbeSettings(spacing_mm=25.0, adaptive=True, adaptive_threshold_mm=0.12,
                           adaptive_max_points=24, max_points_per_area=80)
JOIN_MM = 6.0          # Brennstrecken näher als das ergeben einen Bereich
AREA_PAD_MM = 3.0      # Rand um die Brennstrecke (wie bei der Design-Box)
COVER_TOL_MM = 0.05


class MachinePort(Protocol):
    """Was der Ablauf von der Maschine braucht (Machine-Agent).

    ``status()`` liefert ein Objekt mit ``homed``, ``emergency_latched``,
    ``workpiece_surface_z`` und ``job`` (``state``, ``line``, ``total``,
    ``error``, ``active``) – wie ``machine.client.MachineStatus``. Alle
    Aufrufe blockieren bis der Pi antwortet und werfen bei Ablehnung.
    """

    def status(self) -> Any: ...
    def home(self) -> str: ...
    def probe_at(self, x: float, y: float) -> str: ...
    def upload_job(self, name: str, gcode: str) -> str: ...
    def start_job(self, name: str) -> str: ...
    def abort_job(self) -> str: ...
    def park(self) -> str: ...
    # optional (Pi mit ``autorun_mesh``): def autorun(self, name: str) -> str


#: Merkmal in ``/api/status`` (``features``-Liste oder -Objekt), mit dem ein Pi
#: meldet, dass ``op=autorun`` selbst abtastet und korrigiert (Vorschlag an Claude).
PI_AUTORUN_FEATURE = "autorun_mesh"


def pi_runs_mesh(status: Any) -> bool:
    """Übernimmt der Pi Abtasten + Höhenkorrektur selbst (``op=autorun``)?"""
    raw = getattr(status, "raw", None)
    feats = raw.get("features") if isinstance(raw, dict) else None
    if isinstance(feats, dict):
        return bool(feats.get(PI_AUTORUN_FEATURE))
    if isinstance(feats, (list, tuple)):
        return PI_AUTORUN_FEATURE in feats
    return False


def pi_probe_progress(status: Any) -> Optional[tuple[int, int]]:
    """``job.probe`` = ``{"done": 3, "total": 12}`` während der Pi abtastet."""
    raw = getattr(status, "raw", None)
    job = raw.get("job") if isinstance(raw, dict) else None
    probe = job.get("probe") if isinstance(job, dict) else None
    if not isinstance(probe, dict):
        return None
    try:
        return int(probe.get("done", 0)), int(probe.get("total", 0))
    except (TypeError, ValueError):
        return None


class ClientMachinePort:
    """:class:`MachinePort` über ``machine.client.LumaCutClient`` (ohne Änderung daran)."""

    def __init__(self, client):
        self.client = client

    def status(self):
        return self.client.status()

    def home(self) -> str:
        return self.client.home()

    def probe_at(self, x: float, y: float) -> str:
        return self.client.focus(float(x), float(y))

    def upload_job(self, name: str, gcode: str) -> str:
        return self.client.upload_job(name, gcode)

    def start_job(self, name: str) -> str:
        # absolut: das Höhenmesh ist in Maschinen-mm, eine Pi-Platzierung würde
        # den Auftrag gegen das Mesh verschieben (siehe offene Fragen)
        return self.client.start_job(name)

    def abort_job(self) -> str:
        return self.client.abort_job()

    def park(self) -> str:
        return self.client.park()

    def autorun(self, name: str) -> str:
        return self.client.autorun_job(name)


class FlowError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class FlowResult:
    state: str = "bereit"
    maps: Optional[HeightMapSet] = None
    export: Optional[FocusExport] = None
    reused_mesh: bool = False
    pi_mesh: bool = False             # Pi hat abgetastet und korrigiert
    probe_points: int = 0
    focus_point: Optional[tuple[float, float]] = None
    job_name: str = ""
    error_code: str = ""
    error: str = ""
    notes: list[str] = field(default_factory=list)
    durations_s: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.state == "fertig"

    def to_dict(self) -> dict:
        r = self.export.report if self.export is not None else None
        return {
            "type": "job_result", "state": self.state, "ok": self.ok,
            "job": self.job_name, "reused_mesh": self.reused_mesh, "pi_mesh": self.pi_mesh,
            "probe_points": self.probe_points,
            "areas": [m.area_id for m in self.maps.maps] if self.maps else [],
            "focus_point": list(self.focus_point) if self.focus_point else None,
            "z_range": [r.z_min, r.z_max] if r is not None and math.isfinite(r.z_min) else None,
            "error": {"code": self.error_code, "message": self.error} if self.error_code else None,
            "notes": list(self.notes),
            "durations_s": {k: round(v, 2) for k, v in self.durations_s.items()},
        }


# ------------------------------------------------------------ Bereiche
def job_burn_rects(gcode: str, join_mm: float = JOIN_MM) -> list[Rect]:
    """Rechtecke um zusammenhängende Brennstrecken (G1 mit S>0), Maschinen-mm.

    Strecken, die näher als ``join_mm`` beieinander liegen, werden zu einem
    Rechteck zusammengefasst; so wird nur geprobt, was der Auftrag wirklich
    brennt (auch bei „Nur Auswahl“).
    """
    boxes: list[list[float]] = []
    x = y = 0.0
    absolute, scale, motion, power = True, 1.0, 0, 0.0
    for raw in gcode.splitlines():
        code = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()
        if not code:
            continue
        words = _WORD.findall(code)
        for k, v in words:
            if k != "G":
                continue
            g = float(v)
            if g == 20: scale = 25.4
            elif g == 21: scale = 1.0
            elif g == 90: absolute = True
            elif g == 91: absolute = False
            elif g in (0, 1): motion = int(g)
        vals = {k: float(v) for k, v in words if k in "XYS"}
        if "S" in vals:
            power = vals["S"]
        if "X" not in vals and "Y" not in vals:
            continue
        nx = (vals["X"] * scale if absolute else x + vals["X"] * scale) if "X" in vals else x
        ny = (vals["Y"] * scale if absolute else y + vals["Y"] * scale) if "Y" in vals else y
        if motion == 1 and power > 0 and (nx, ny) != (x, y):
            boxes.append([min(x, nx), min(y, ny), max(x, nx), max(y, ny)])
        x, y = nx, ny
    return [Rect(*b) for b in _merge_boxes(boxes, join_mm)]


def _merge_boxes(boxes: list[list[float]], gap: float) -> list[list[float]]:
    merged = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        for b in merged:
            for o in out:
                if (b[0] <= o[2] + gap and o[0] <= b[2] + gap and
                        b[1] <= o[3] + gap and o[1] <= b[3] + gap):
                    o[0], o[1] = min(o[0], b[0]), min(o[1], b[1])
                    o[2], o[3] = max(o[2], b[2]), max(o[3], b[3])
                    changed = True
                    break
            else:
                out.append(b)
        merged = out
    # Linien (Breite/Höhe 0) bekommen eine Mindestfläche
    return [[b[0], b[1], max(b[2], b[0] + 0.1), max(b[3], b[1] + 0.1)] for b in merged]


def job_probe_areas(gcode: str, objects: Sequence = ()) -> tuple[list[ProbeArea], list[str]]:
    """Probe-Bereiche aus dem Auftrag: erkannte Werkstücke unter der Brennstrecke,
    sonst die Brennstrecken-Box + Rand. Keine manuelle Auswahl nötig."""
    rects = job_burn_rects(gcode)
    if not rects:
        return [], []
    areas, notes = areas_from_design_bounds(rects, objects, pad_mm=AREA_PAD_MM)
    if not objects:
        notes = []  # ohne Kamera-Scan ist die Box der Normalfall, kein Hinweis nötig
    return areas, notes


def lowest_measured_point(maps: HeightMapSet) -> Optional[tuple[float, float, float]]:
    best: Optional[tuple[float, float, float]] = None
    for m in maps.maps:
        X, Y = np.meshgrid(m.xs, m.ys)
        ok = np.isfinite(m.z)
        if not ok.any():
            continue
        k = int(np.argmin(np.where(ok, m.z, np.inf)))
        j, i = np.unravel_index(k, m.z.shape)
        cand = (float(X[j, i]), float(Y[j, i]), float(m.z[j, i]))
        if best is None or cand[2] < best[2]:
            best = cand
    return best


def mesh_reusable(maps: Optional[HeightMapSet], gcode: str, now: Optional[float] = None,
                  max_age_h: float = MAX_AGE_H) -> tuple[bool, str]:
    """Darf ``maps`` (nach Kontrollmessung) für diesen Auftrag wiederverwendet werden?"""
    if maps is None or not maps.maps:
        return False, "kein Höhenmesh vorhanden"
    now = time.time() if now is None else now
    if not maps.created or (now - maps.created) / 3600 > max_age_h:
        return False, f"Höhenmesh älter als {max_age_h:g} h oder ohne Zeitstempel"
    cov = job_coverage(gcode, maps)
    if cov.burn_mm <= 0 or cov.outside_mm > COVER_TOL_MM:
        return False, "Höhenmesh deckt den Auftrag nicht vollständig ab"
    return True, ""


# ------------------------------------------------------------ Ablauf
class OneClickJob:
    """Zustandsmaschine für den Ein-Klick-Auftrag (siehe Moduldoku)."""

    def __init__(self, machine: MachinePort, workflow, *,
                 control: Optional[RunControl] = None,
                 on_event: Optional[Callable[[dict], None]] = None,
                 probe_settings: ProbeSettings = FAST_PROBE,
                 poll_s: float = 0.5, max_status_errors: int = 20,
                 always_home: bool = False, use_pi_mesh: Optional[bool] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.machine = machine
        self.workflow = workflow
        self.control = control or getattr(workflow, "control", None) or RunControl()
        self.on_event = on_event
        self.probe_settings = probe_settings
        self.poll_s = poll_s
        self.max_status_errors = max_status_errors
        self.always_home = always_home
        # None = automatisch aus /api/status; False = Studio misst immer selbst
        self.use_pi_mesh = use_pi_mesh
        self._sleep = sleep
        self._clock = clock
        self.state = "bereit"
        self.history: list[str] = []
        self.result = FlowResult()
        self._homed_by_us = False

    # ---- Steuerung (beliebiger Thread) --------------------------------
    def pause(self) -> None:
        self.control.pause()

    def resume(self) -> None:
        self.control.resume()

    def cancel(self) -> None:
        self.control.cancel()

    # ---- Ereignisse ---------------------------------------------------
    def _emit(self, message: str, progress: Optional[float] = None, **extra) -> None:
        ev = {"type": "job_state", "state": self.state, "label": STATE_LABELS[self.state],
              "step": STEPS.index(self.state) + 1 if self.state in STEPS else None,
              "steps": len(STEPS), "message": message,
              "progress": None if progress is None else round(float(progress), 4),
              "paused": self.control.paused}
        ev.update(extra)
        if self.on_event is not None:
            self.on_event(ev)

    def _enter(self, state: str, message: str, **extra) -> None:
        self.state = state
        self.history.append(state)
        self._emit(message, 0.0 if state in STEPS else None, **extra)

    def _checkpoint(self) -> None:
        if self.control.paused:
            self._emit("Pausiert – „Fortsetzen“ oder „Abbrechen“", paused=True)
        self.control.checkpoint()

    def _on_probe_progress(self, p: Progress) -> None:
        if self.state == "probing":
            self._emit(p.message or f"Messpunkt {p.done}/{p.total}", p.fraction,
                       eta_s=None if p.eta_s is None else round(p.eta_s, 1))

    # ---- Hauptablauf --------------------------------------------------
    def run(self, gcode: str, name: str = "auftrag.gcode", *, objects: Sequence = (),
            mosaic=None, saved_maps: Optional[HeightMapSet] = None) -> FlowResult:
        res = self.result = FlowResult(job_name=name)
        self.history = []
        self._homed_by_us = self._job_started = False
        self._parked_note = ""
        t0 = self._clock()
        step_t = t0
        try:
            st = self._precheck(gcode)
            pi_mesh = (self.use_pi_mesh if self.use_pi_mesh is not None else pi_runs_mesh(st)) \
                and hasattr(self.machine, "autorun")
            if pi_mesh:
                res.pi_mesh = True
                self._run_on_pi(gcode, name)
                self._finish_park()
                self._enter("fertig", "Auftrag fertig, Kopf geparkt")
                return self._finish(res, t0)
            for step in STEPS:
                now = self._clock()
                if self.state in STEPS:
                    res.durations_s[self.state] = now - step_t
                step_t = now
                if step == "referenzieren":
                    self._home(st)
                elif step == "probing":
                    self._probe(gcode, objects, mosaic, saved_maps)
                elif step == "fokus":
                    self._focus(gcode, mosaic)
                elif step == "job":
                    self._run_job(name)
                else:
                    self._finish_park()
            res.durations_s["parken"] = self._clock() - step_t
            self._enter("fertig", "Auftrag fertig, Kopf geparkt")
        except Cancelled:
            self._stop_before_job()
            res.error_code, res.error = "cancelled", "Vom Nutzer abgebrochen"
            self._enter("abgebrochen", "Abgebrochen" + self._park_note())
        except FlowError as exc:
            self._stop_before_job()
            res.error_code, res.error = exc.code, str(exc)
            self._enter("fehler", str(exc) + self._park_note(), error={"code": exc.code,
                                                                      "message": str(exc)})
        return self._finish(res, t0)

    def _finish(self, res: FlowResult, t0: float) -> FlowResult:
        res.durations_s["gesamt"] = self._clock() - t0
        res.state = self.state
        return res

    # ---- Schritte -----------------------------------------------------
    def _status(self):
        try:
            st = self.machine.status()
        except Exception as exc:  # noqa: BLE001
            raise FlowError("not_ready", f"Pi-Status nicht lesbar: {exc}") from exc
        if st.emergency_latched:
            raise FlowError("emergency", "Notstopp aktiv – Ursache beseitigen und quittieren")
        return st

    def _precheck(self, gcode: str) -> None:
        errors = precheck_gcode(gcode)
        if errors:
            raise FlowError("invalid_job", " ".join(errors))
        if not job_burn_rects(gcode):
            raise FlowError("invalid_job", "Der Auftrag enthält keine Brennstrecke.")
        st = self._status()
        if st.job.active:
            raise FlowError("not_ready", "Auf dem Pi läuft bereits ein Auftrag")
        return st

    def _home(self, st) -> None:
        if st.homed and not self.always_home:
            self._enter("referenzieren", "Bereits referenziert – Referenzfahrt nicht nötig")
            self._emit("Bereits referenziert", 1.0)
            return
        self._enter("referenzieren", "Referenzfahrt: X/Y, dann Z, Rückzug …")
        self._checkpoint()
        try:
            self.machine.home()
        except Exception as exc:  # noqa: BLE001
            raise FlowError("homing_failed", f"Referenzfahrt fehlgeschlagen: {exc}") from exc
        self._homed_by_us = True
        if not self._status().homed:
            raise FlowError("homing_failed", "Maschine meldet nach der Referenzfahrt "
                            "„nicht referenziert“")
        self._checkpoint()

    def _probe(self, gcode: str, objects: Sequence, mosaic, saved: Optional[HeightMapSet]) -> None:
        res = self.result
        wf = self.workflow
        self._enter("probing", "Höhenmesh: Bereiche aus dem Auftrag bestimmen …")
        wf.control = self.control
        old_cb = self.control.on_progress
        self.control.on_progress = self._on_probe_progress
        old_settings = wf.settings
        wf.settings = replace(self.probe_settings)
        try:
            ok, why = mesh_reusable(saved, gcode)
            if ok:
                self._emit("Vorhandenes Höhenmesh: Kontrollmessung (3 Punkte je Bereich) …", 0.0)
                reused, notes = wf.try_reuse(saved, mosaic, spot_checks=3)
                res.notes += notes
                if reused:
                    res.maps, res.reused_mesh = saved, True
                    res.probe_points = sum(min(3, m.measured_count) for m in saved.maps)
                    self._emit("Höhenmesh wiederverwendet (Material unverändert)", 1.0)
                    return
                self._emit("Material verändert – Höhenmesh wird neu gemessen", 0.0)
            elif saved is not None and saved.maps:
                res.notes.append(f"Gespeichertes Höhenmesh nicht verwendet: {why}.")
            areas, notes = job_probe_areas(gcode, objects)
            res.notes += notes
            job = wf.plan_probe(areas, (0.0, 0.0))
            res.notes += job.warnings
            if not job.points:
                raise FlowError("probe_failed", "Keine erreichbaren Messpunkte unter dem Motiv"
                                + (" (" + "; ".join(job.warnings) + ")" if job.warnings else ""))
            self._emit(f"Höhenmesh: {len(job.points)} Messpunkte in {len(areas)} Bereich(en) …", 0.0)
            probe: ProbeResult = wf.probe_areas(job, (0.0, 0.0), mosaic)
            res.probe_points = probe.probes
            if not probe.ok:
                raise FlowError("probe_failed", "Kein Kontakt in mindestens einem Bereich – "
                                "liegt Material unter dem Motiv? Taster prüfen.")
            res.maps = probe.maps
            self._emit(f"Höhenmesh fertig: {probe.probes} Messungen"
                       + (f", {probe.adaptive_points} verfeinert" if probe.adaptive_points else ""), 1.0)
        except (Cancelled, FlowError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise FlowError("probe_failed", f"Proben fehlgeschlagen: {exc}") from exc
        finally:
            self.control.on_progress = old_cb
            wf.settings = old_settings

    def _focus(self, gcode: str, mosaic) -> None:
        res = self.result
        self._enter("fokus", "Fokus: G30 am niedrigsten Messpunkt …")
        self._checkpoint()
        low = lowest_measured_point(res.maps)
        if low is None:
            raise FlowError("focus_failed", "Höhenmesh enthält keine Messwerte")
        x, y, _z = low
        try:
            self.machine.probe_at(x, y)
        except Exception as exc:  # noqa: BLE001
            raise FlowError("focus_failed", f"Fokusmessung bei X{x:.1f} Y{y:.1f} fehlgeschlagen: {exc}") from exc
        res.focus_point = (x, y)
        surface = self._status().workpiece_surface_z
        use_mosaic = mosaic if res.maps.fingerprints else None
        export = compensate_for_export(gcode, res.maps, mosaic=use_mosaic, pi_surface_z=surface)
        res.export = export
        if not export.ok:
            raise FlowError("focus_failed", "Fokuskorrektur nicht möglich: " + " ".join(export.errors))
        # Warnungen werden hier automatisch behandelt: Mesh ist frisch gemessen
        # bzw. kontrolliert; außerhalb der Bereiche gilt die höchste Oberfläche.
        res.notes += [w for w in export.warnings
                      if "Kein aktueller Scan" not in w and "Fingerabdruck" not in w]
        r = export.report
        self._emit(f"Fokuskorrektur: Z {r.z_min:.2f} … {r.z_max:.2f} mm", 1.0)
        self._checkpoint()

    def _run_job(self, name: str) -> None:
        self._enter("job", f"Lade {name} hoch …")
        self._checkpoint()
        try:
            self.machine.upload_job(name, self.result.export.gcode)
            self._checkpoint()
            self.machine.start_job(name)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FlowError("upload_failed", f"Auftrag abgelehnt: {exc}") from exc
        self._job_started = True
        self._emit(f"{name} läuft", 0.0)
        self._poll_job(name, pi_mesh=False)

    def _run_on_pi(self, gcode: str, name: str) -> None:
        """Pi mit ``autorun_mesh``: hochladen, ``op=autorun``, Pi-Zustände spiegeln."""
        self._enter("referenzieren", f"Lade {name} hoch – der Pi referenziert, tastet ab und lasert")
        self._checkpoint()
        try:
            self.machine.upload_job(name, gcode)
            self._checkpoint()
            self.machine.autorun(name)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FlowError("upload_failed", f"Auftrag abgelehnt: {exc}") from exc
        self._job_started = True
        self._poll_job(name, pi_mesh=True)

    def _poll_job(self, name: str, pi_mesh: bool) -> None:
        errors = 0
        seen_active = False
        while True:
            if self.control.cancelled:
                self._abort_running()
                raise Cancelled()
            self._sleep(self.poll_s)
            try:
                st = self.machine.status()
                errors = 0
            except Exception as exc:  # noqa: BLE001
                errors += 1
                if errors >= self.max_status_errors:
                    raise FlowError("connection_lost", f"Kein Status vom Pi ({exc}) – der Auftrag "
                                    "läuft dort evtl. weiter. NOT-AUS bereithalten.") from exc
                continue
            if st.emergency_latched:
                raise FlowError("emergency", "Notstopp während des Auftrags")
            job = st.job
            if job.file and job.file != name:
                raise FlowError("job_failed", f"Auf dem Pi läuft ein anderer Auftrag ({job.file})")
            if job.active:
                seen_active = True
                if pi_mesh and job.state == "homing":
                    if self.state != "referenzieren":
                        self._enter("referenzieren", "Pi: Referenzfahrt …")
                    continue
                if pi_mesh and job.state == "probing":
                    if self.state != "probing":
                        self._enter("probing", "Pi: Höhenmesh messen …")
                    pr = pi_probe_progress(st)
                    if pr and pr[1]:
                        self._emit(f"Pi: Messpunkt {pr[0]}/{pr[1]}", pr[0] / pr[1])
                        self.result.probe_points = pr[0]
                    continue
                if pi_mesh and self.state in ("referenzieren", "probing"):
                    self._enter("fokus", "Pi: Fokus/Höhenkorrektur übernommen")
                    self._enter("job", f"{name} läuft")
                if job.total and job.line >= job.total:
                    if self.state != "parken":
                        self._enter("parken", "Brennen fertig – Pi parkt (Laser aus, Z hoch, X0/Y0)")
                else:
                    self._emit(f"Zeile {job.line}/{job.total}", job.progress)
                continue
            if job.state == "complete":
                return
            if job.state == "aborted":
                raise Cancelled()
            if job.state == "error":
                code = "job_failed"
                if pi_mesh and self.state == "probing":
                    code = "probe_failed"
                elif pi_mesh and self.state == "referenzieren":
                    code = "homing_failed"
                raise FlowError(code, f"Auftrag abgebrochen: {job.error or 'Fehler'} "
                                "(Pi: Laser aus, geparkt)")
            if seen_active:
                raise FlowError("job_failed", f"Unerwarteter Auftragszustand „{job.state}“")

    def _finish_park(self) -> None:
        if self.state != "parken":
            self._enter("parken", "Pi hat am Auftragsende geparkt")

    # ---- Aufräumen ----------------------------------------------------
    def _abort_running(self) -> None:
        try:
            self.machine.abort_job()
        except Exception:  # noqa: BLE001 - Auftrag ist evtl. schon zu Ende
            pass
        for _ in range(self.max_status_errors * 4):
            try:
                if not self.machine.status().job.active:
                    break
            except Exception:  # noqa: BLE001
                pass
            self._sleep(self.poll_s)

    _job_started = False
    _parked_note = ""

    def _stop_before_job(self) -> None:
        """Nach Fehler/Abbruch vor dem Lasern: parken, wenn sicher möglich.
        Lief der Auftrag schon, parkt der Pi selbst (``_stop_after_job_error``)."""
        self._parked_note = ""
        if self._job_started or not self._homed_by_us:
            return
        try:
            st = self.machine.status()
            if st.emergency_latched or not st.homed:
                return
            self.machine.park()
            self._parked_note = " – Kopf geparkt"
        except Exception as exc:  # noqa: BLE001 - z. B. alter Pi ohne op=park
            self._parked_note = f" – Parken nicht möglich ({exc})"

    def _park_note(self) -> str:
        return self._parked_note
