"""Import-Einstellungen: Konturen gleich beim Import aufräumen (Qt-frei).

Wie LightBurns *Auto-close tolerance* der DXF-Import-Einstellungen (lose Strecken
aus CAD-Programmen werden beim Import zu Pfaden verbunden) und wie LightBurn,
das einen SVG-Pfad mit seinen Löchern als *eine* Form importiert. LumaCut legt
beim Import jede Teilkontur als eigenes Objekt an; bisher zeigte die Statusleiste
nur, wie viele offene / verbindbare Konturen und wie viele Löcher als eigene
Objekte dabei sind, und das Aufräumen war ein eigener Schritt (Pfad › „Pfade
verbinden“, „Kombinieren“, „Duplikate löschen“).

:class:`ImportOptions` – alle Schalter sind **standardmäßig aus**, damit jeder
Import ohne Einstellung genau so bleibt wie bisher (gleiche Objekte, gleicher
G-Code). Eingeschaltet laufen die Schritte in dieser Reihenfolge:

1. ``delete_duplicates`` – doppelt übereinanderliegende Konturen der Datei
   löschen (:func:`pathjoin.find_duplicates`, 0,01 mm, unabhängig von Start und
   Richtung) – vor dem Verbinden, damit eine doppelte DXF-Strecke keine
   falsche Kette bildet und nicht doppelt gelasert wird;
2. ``auto_join`` – offene Pfade / Linien, deren Enden höchstens
   ``join_tolerance_mm`` auseinanderliegen, zu Ketten verbinden; geschlossene
   Ketten werden Polygone, ineinanderliegende Ketten Polygone mit Loch
   (:func:`pathjoin.auto_join`, wie „Pfade verbinden“ Alt+J);
3. ``combine_holes`` – geschlossene Einzelkonturen (Polygone mit einem Ring),
   die in einer anderen liegen, mit ihrer Außenkontur zu *einem* Polygon mit
   Loch kombinieren (Gerade-Ungerade-Regel wie die Füllung; Inseln in Löchern
   bleiben eigene Objekte), damit „Füllen: Jedes Objekt einzeln“ das Loch
   eines „O“ oder eines Logos frei lässt (:func:`pathsplit.combine` je Gruppe).

Nur die Objekte der importierten Datei werden betrachtet (nie bestehende
Objekte des Dokuments), Ebene und Import-Gruppe bleiben, erzeugte Objekte
(Codes) und Bilder werden nie verändert.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lumacut_canvas import pathjoin, pathsplit
from lumacut_canvas.model import Shape

JOIN_TOLERANCE_MM = pathjoin.JOIN_TOLERANCE_MM        # 0,05 mm wie LightBurn
JOIN_TOLERANCE_RANGE = (0.001, 2.0)                   # mm
COMBINE_MAX = 2000         # mehr geschlossene Konturen: Löcher nicht kombinieren (Verschachtelung O(n²))

SETTINGS_KEYS = {
    "delete_duplicates": "import/delete_duplicates",
    "auto_join": "import/auto_join",
    "join_tolerance_mm": "import/join_tolerance_mm",
    "combine_holes": "import/combine_holes",
}


def _clamp_tol(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return JOIN_TOLERANCE_MM
    if v != v:   # NaN
        return JOIN_TOLERANCE_MM
    lo, hi = JOIN_TOLERANCE_RANGE
    return min(max(v, lo), hi)


@dataclass
class ImportOptions:
    delete_duplicates: bool = False
    auto_join: bool = False
    join_tolerance_mm: float = JOIN_TOLERANCE_MM
    combine_holes: bool = False

    def normalized(self) -> "ImportOptions":
        return ImportOptions(bool(self.delete_duplicates), bool(self.auto_join),
                             _clamp_tol(self.join_tolerance_mm), bool(self.combine_holes))

    @property
    def active(self) -> bool:
        return self.delete_duplicates or self.auto_join or self.combine_holes

    def describe(self) -> str:
        """Kurzer Text der eingeschalteten Schritte (Menü-Tooltip / Statusleiste)."""
        parts = []
        if self.delete_duplicates:
            parts.append("Duplikate löschen")
        if self.auto_join:
            parts.append(f"verbinden ≤ {self.join_tolerance_mm:g} mm")
        if self.combine_holes:
            parts.append("Löcher kombinieren")
        return ", ".join(parts) if parts else "aus"


def _to_bool(v, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def load_options(settings) -> ImportOptions:
    """Gespeicherte Import-Einstellungen (ohne QSettings / ohne Eintrag: alles aus)."""
    if settings is None:
        return ImportOptions()
    def get(name):
        key = SETTINGS_KEYS[name]
        return settings.value(key) if settings.contains(key) else None
    return ImportOptions(
        _to_bool(get("delete_duplicates"), False),
        _to_bool(get("auto_join"), False),
        _clamp_tol(get("join_tolerance_mm") if get("join_tolerance_mm") is not None
                   else JOIN_TOLERANCE_MM),
        _to_bool(get("combine_holes"), False),
    ).normalized()


def save_options(settings, options: ImportOptions) -> None:
    if settings is None:
        return
    o = options.normalized()
    settings.setValue(SETTINGS_KEYS["delete_duplicates"], o.delete_duplicates)
    settings.setValue(SETTINGS_KEYS["auto_join"], o.auto_join)
    settings.setValue(SETTINGS_KEYS["join_tolerance_mm"], o.join_tolerance_mm)
    settings.setValue(SETTINGS_KEYS["combine_holes"], o.combine_holes)
    settings.sync()


@dataclass
class CleanupResult:
    shapes: list[Shape] = field(default_factory=list)
    duplicates: int = 0          # gelöschte doppelte Konturen
    joined_pieces: int = 0       # verbrauchte offene Formen (verbunden / geschlossen)
    joined_closed: int = 0       # daraus geschlossene Konturen
    joined_open: int = 0         # daraus längere offene Ketten
    holes: int = 0               # mit ihrer Außenkontur kombinierte Löcher
    combine_skipped: bool = False  # zu viele Konturen – Löcher nicht kombiniert

    @property
    def changed(self) -> bool:
        return bool(self.duplicates or self.joined_pieces or self.joined_closed or self.holes)

    def note(self) -> str:
        """Text für die Statusleiste („" wenn nichts geändert wurde)."""
        parts = []
        if self.duplicates:
            parts.append(f"{self.duplicates} Duplikat(e) gelöscht")
        if self.joined_pieces or self.joined_closed:
            text = f"{self.joined_pieces} offene Form(en) verbunden"
            made = []
            if self.joined_closed:
                made.append(f"{self.joined_closed} geschlossen")
            if self.joined_open:
                made.append(f"{self.joined_open} offen")
            if made:
                text += " → " + ", ".join(made)
            parts.append(text)
        if self.holes:
            parts.append(f"{self.holes} Loch-Kontur(en) mit Außenkontur kombiniert")
        if self.combine_skipped:
            parts.append(f"über {COMBINE_MAX} Konturen – Löcher nicht kombiniert")
        if not parts:
            return ""
        return " · beim Import: " + ", ".join(parts)


def _replace(shapes: list[Shape], remove: set[str], groups: list[tuple[list[str], list[Shape]]]
             ) -> list[Shape]:
    """Objektliste mit ersetzten Objekten: jede neue Form steht an der Stelle des
    ersten ersetzten Objekts ihrer Gruppe (Dokumentreihenfolge bleibt sonst gleich)."""
    at: dict[str, list[Shape]] = {}
    for old_ids, new in groups:
        first = next((s.id for s in shapes if s.id in set(old_ids)), None)
        if first is not None:
            at.setdefault(first, []).extend(new)
    out: list[Shape] = []
    for s in shapes:
        if s.id in at:
            out.extend(at[s.id])
        if s.id not in remove:
            out.append(s)
    return out


def _single_ring_polygon(s: Shape) -> bool:
    return (s.kind == "polygon" and not s.generator and len(s.points) >= 3
            and len(s.ring_ranges()) == 1)


def _combine_holes(shapes: list[Shape], res: CleanupResult) -> list[Shape]:
    by_layer: dict[str, list[Shape]] = {}
    for s in shapes:
        if _single_ring_polygon(s):
            by_layer.setdefault(s.layer_id, []).append(s)
    if sum(len(v) for v in by_layer.values()) > COMBINE_MAX:
        res.combine_skipped = True
        return shapes
    remove: set[str] = set()
    groups: list[tuple[list[str], list[Shape]]] = []
    for members in by_layer.values():
        if len(members) < 2:
            continue
        rings = []
        for s in members:
            world, _conv = pathsplit._world_rings(s)
            rings.append(world[0][0])
        for grp in pathjoin.nest_rings(rings):
            if len(grp) < 2:
                continue
            parts = [members[i] for i in grp]          # Außenkontur zuerst, dann Löcher
            combined = pathsplit.combine(parts)
            if not combined.changed:
                continue
            ids, new = combined.groups[0]
            remove.update(ids)
            groups.append((ids, [new]))
            res.holes += len(grp) - 1
    if not groups:
        return shapes
    return _replace(shapes, remove, groups)


def clean_import(shapes: list[Shape], options: ImportOptions | None) -> CleanupResult:
    """Importierte Objekte nach ``options`` aufräumen (siehe Moduldoku).

    Ohne eingeschaltete Option kommt genau dieselbe Liste (dieselben Objekte) zurück."""
    shapes = list(shapes)
    res = CleanupResult(shapes)
    if options is None:
        return res
    o = options.normalized()
    if not o.active or not shapes:
        return res
    if o.delete_duplicates:
        dupes = set(pathjoin.find_duplicates(shapes))
        if dupes:
            shapes = [s for s in shapes if s.id not in dupes]
            res.duplicates = len(dupes)
    if o.auto_join:
        joined = pathjoin.auto_join(shapes, o.join_tolerance_mm)
        if joined.remove:
            shapes = _replace(shapes, set(joined.remove), [(list(joined.remove), list(joined.add))])
            res.joined_pieces = len(joined.remove)
            res.joined_closed = joined.closed
            res.joined_open = joined.open_chains
    if o.combine_holes:
        shapes = _combine_holes(shapes, res)
    res.shapes = shapes
    return res
