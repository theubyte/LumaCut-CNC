"""Geführter Ablauf Home → Scan → Markieren → Probe → Fokus → Rahmen → Auftrag → Parken.

Qt-frei: ``evaluate(facts, marks)`` berechnet aus einem Schnappschuss des
Maschinen-/Studio-Zustands (``WorkflowFacts``) und den Benutzer-Markierungen
(erledigt/übersprungen) den Status jedes Schritts. Die Oberfläche
(``lumacut_workflow.qt``) liest nur noch die Fakten aus und führt die
vorhandenen Aktionen aus (MachinePanel/ScanPanel/Senden), es gibt keine
eigene Maschinenlogik.

Status je Schritt:
* ``done``    – erledigt (aus dem Maschinenstatus oder nach erfolgreicher Aktion)
* ``ready``   – Voraussetzungen erfüllt, kann ausgeführt werden
* ``blocked`` – Voraussetzung fehlt (``reason`` sagt welche)
* ``skipped`` – vom Benutzer übersprungen
* ``running`` – läuft gerade (Maschine/Scan beschäftigt mit genau diesem Schritt)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

DONE, READY, BLOCKED, SKIPPED, RUNNING = "done", "ready", "blocked", "skipped", "running"

#: Pi job.state-Werte, in denen ein Auftrag läuft (wie machine.client + Pause)
JOB_RUNNING_STATES = ("homing", "probing", "running", "paused")

STATUS_LABELS = {
    DONE: "erledigt",
    READY: "bereit",
    BLOCKED: "gesperrt",
    SKIPPED: "übersprungen",
    RUNNING: "läuft …",
}


@dataclass(frozen=True)
class StepDef:
    key: str
    title: str
    hint: str
    skippable: bool = True


STEPS: tuple[StepDef, ...] = (
    StepDef("home", "Referenzfahrt", "Maschine referenzieren (Home), damit Koordinaten stimmen.",
            skippable=False),
    StepDef("scan", "Scan", "Arbeitsfläche mit der Kamera abfahren (Hintergrundbild + Werkstücke)."),
    StepDef("mark", "Markieren", "Werkstücke in der Scan-Liste anhaken oder das Design darauf platzieren."),
    StepDef("probe", "Probe", "Höhenmesh der markierten Bereiche messen (für Fokuskorrektur)."),
    StepDef("focus", "Fokus", "Werkstückoberfläche antasten (G30) – setzt die Fokushöhe."),
    StepDef("frame", "Rahmen", "Umriss mit ausgeschaltetem Laser abfahren und Lage prüfen."),
    StepDef("job", "Auftrag", "G-Code senden und Auftrag starten.", skippable=False),
    StepDef("park", "Parken", "Kopf in die Parkposition fahren."),
)
STEP_KEYS = tuple(s.key for s in STEPS)
_BY_KEY = {s.key: s for s in STEPS}


def step_def(key: str) -> StepDef:
    return _BY_KEY[key]


@dataclass(frozen=True)
class WorkflowFacts:
    """Schnappschuss – alles, was die Schritte entscheiden müssen."""

    connected: bool = False           # Pi verbunden, Status frisch
    homed: bool = False
    emergency: bool = False           # Notstopp verriegelt
    machine_busy: bool = False        # Auftrag/Rahmen/Befehl läuft
    machine_activity: str = ""        # "job" | "frame" | "command" | ""
    job_state: str = "idle"           # Pi job.state
    frame_state: str = "idle"         # Pi frame.state („complete“ setzt der Adapter
                                      # nur bei einem Übergang als erledigt)
    surface_z: float | None = None    # Pi workpiece_surface_z (nach Fokus/G30)
    design_empty: bool = True         # keine sichtbaren, brennbaren Formen
    simulation: bool = False          # Scan/Probe im Simulationsmodus (ohne Pi)
    scan_busy: bool = False
    scan_kind: str = ""               # "scan" | "probe" | "full" während scan_busy
    has_mosaic: bool = False
    marked_areas: int = 0             # angehakte Werkstücke bzw. Design-Bereiche
    has_maps: bool = False            # Höhenmesh vorhanden


@dataclass
class WorkflowMarks:
    """Benutzer-Entscheidungen (nicht aus der Maschine ablesbar)."""

    skipped: set[str] = field(default_factory=set)
    done: set[str] = field(default_factory=set)   # z. B. Rahmen/Parken nach erfolgreicher Aktion

    def skip(self, key: str) -> None:
        if not step_def(key).skippable:
            raise ValueError(f"{step_def(key).title} kann nicht übersprungen werden")
        self.skipped.add(key)
        self.done.discard(key)

    def unskip(self, key: str) -> None:
        self.skipped.discard(key)

    def mark_done(self, key: str) -> None:
        step_def(key)
        self.done.add(key)
        self.skipped.discard(key)

    def invalidate(self, keys: Iterable[str]) -> None:
        for k in keys:
            self.done.discard(k)

    def reset(self) -> None:
        self.skipped.clear()
        self.done.clear()


@dataclass(frozen=True)
class StepState:
    key: str
    title: str
    status: str
    reason: str = ""

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def finished(self) -> bool:
        return self.status in (DONE, SKIPPED)


def _machine_block(f: WorkflowFacts, need_home: bool = True) -> str:
    if f.emergency:
        return "Notstopp verriegelt – zuerst quittieren"
    if not f.connected:
        return "Nicht mit dem Pi verbunden"
    if need_home and not f.homed:
        return "Zuerst referenzieren (Home)"
    if f.machine_busy:
        return "Maschine beschäftigt"
    return ""


def _scan_block(f: WorkflowFacts) -> str:
    if f.scan_busy:
        return "Scan/Probe läuft bereits"
    if f.simulation:
        return ""
    return _machine_block(f)


def evaluate(f: WorkflowFacts, marks: WorkflowMarks | None = None) -> list[StepState]:
    marks = marks or WorkflowMarks()
    out: list[StepState] = []

    def add(key: str, status: str, reason: str = "") -> None:
        if key in marks.skipped and status != RUNNING:
            status, reason = SKIPPED, ""
        out.append(StepState(key, step_def(key).title, status, reason))

    # Home ------------------------------------------------------------
    if f.homed and not f.emergency:
        add("home", DONE)
    else:
        why = _machine_block(f, need_home=False)
        add("home", BLOCKED if why else READY, why)

    # Scan ------------------------------------------------------------
    if f.scan_busy and f.scan_kind in ("scan", "full"):
        add("scan", RUNNING)
    elif f.has_mosaic:
        add("scan", DONE)
    else:
        why = _scan_block(f)
        add("scan", BLOCKED if why else READY, why)

    # Markieren ---------------------------------------------------------
    scan_ok = f.has_mosaic or "scan" in marks.skipped
    if f.marked_areas > 0:
        add("mark", DONE)
    elif not scan_ok and f.design_empty:
        add("mark", BLOCKED, "Erst scannen oder ein Design platzieren")
    else:
        add("mark", READY, "Werkstück in der Scan-Liste anhaken oder Design platzieren")

    # Probe -------------------------------------------------------------
    if f.scan_busy and f.scan_kind in ("probe", "full"):
        add("probe", RUNNING)
    elif f.has_maps:
        add("probe", DONE)
    elif f.marked_areas == 0:
        add("probe", BLOCKED, "Keine markierten Bereiche")
    else:
        why = _scan_block(f)
        add("probe", BLOCKED if why else READY, why)

    # Fokus ---------------------------------------------------------------
    if f.surface_z is not None and f.homed:
        add("focus", DONE)
    else:
        why = _machine_block(f)
        add("focus", BLOCKED if why else READY, why)

    # Rahmen --------------------------------------------------------------
    if f.machine_activity == "frame" or f.frame_state == "running":
        add("frame", RUNNING)
    elif "frame" in marks.done:
        add("frame", DONE)
    elif f.design_empty:
        add("frame", BLOCKED, "Kein Design auf der Arbeitsfläche")
    else:
        why = _machine_block(f)
        add("frame", BLOCKED if why else READY, why)

    # Auftrag -------------------------------------------------------------
    if f.job_state in JOB_RUNNING_STATES or f.machine_activity == "job":
        add("job", RUNNING)
    elif "job" in marks.done:
        add("job", DONE)
    elif f.design_empty:
        add("job", BLOCKED, "Kein Design auf der Arbeitsfläche")
    else:
        why = _machine_block(f)
        if not why:
            pending = [s.title for s in out if s.key in ("focus", "frame") and not s.finished]
            if pending:
                why = "Erst " + " und ".join(pending) + " erledigen oder überspringen"
        add("job", BLOCKED if why else READY, why)

    # Parken --------------------------------------------------------------
    if "park" in marks.done:
        add("park", DONE)
    else:
        why = _machine_block(f)
        add("park", BLOCKED if why else READY, why)
    return out


def current_step(states: list[StepState]) -> StepState | None:
    """Erster nicht erledigter/übersprungener Schritt (der „nächste“)."""
    for s in states:
        if not s.finished:
            return s
    return None


def summary(states: list[StepState]) -> str:
    done = sum(1 for s in states if s.finished)
    cur = current_step(states)
    if cur is None:
        return f"Ablauf abgeschlossen ({done}/{len(states)})"
    tail = f" – {cur.reason}" if cur.status == BLOCKED and cur.reason else ""
    return f"Nächster Schritt: {cur.title} ({cur.label}){tail} · {done}/{len(states)} erledigt"


__all__ = [
    "DONE", "READY", "BLOCKED", "SKIPPED", "RUNNING", "STATUS_LABELS",
    "StepDef", "STEPS", "STEP_KEYS", "step_def", "WorkflowFacts", "WorkflowMarks",
    "StepState", "JOB_RUNNING_STATES", "evaluate", "current_step", "summary", "replace",
]
