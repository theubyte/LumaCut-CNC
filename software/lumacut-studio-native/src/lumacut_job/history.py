"""Auftragsverlauf: zuletzt gesendete G-Code-Aufträge (Qt-frei).

Jeder gesendete Auftrag wird als Datei im Verlaufsordner abgelegt
(``LUMACUT_HISTORY_DIR`` oder AppData/``history``), dazu ein ``index.json``
mit Name, Zeit und Kurzschätzung. Es werden höchstens :data:`MAX_ENTRIES`
Aufträge behalten; ältere Dateien werden gelöscht.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_ENTRIES = 20
INDEX = "index.json"


@dataclass(frozen=True)
class HistoryEntry:
    name: str        # Name, unter dem der Auftrag gesendet wurde (z. B. "schild.gcode")
    file: str        # Dateiname im Verlaufsordner
    sent_at: float   # Unix-Zeit
    summary: str = ""
    lines: int = 0

    def label(self) -> str:
        t = time.strftime("%d.%m.%Y %H:%M", time.localtime(self.sent_at))
        return f"{t}  {self.name}" + (f"  – {self.summary}" if self.summary else "")


def _safe(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[:60].strip("._") or "auftrag"
    return stem if stem.lower().endswith((".gcode", ".gc", ".nc")) else stem + ".gcode"


class JobHistory:
    def __init__(self, directory: str | Path, max_entries: int = MAX_ENTRIES):
        self.dir = Path(directory)
        self.max_entries = max_entries

    # ------------------------------------------------------------ index
    def entries(self) -> list[HistoryEntry]:
        """Neueste zuerst; fehlende Dateien werden übersprungen."""
        try:
            raw = json.loads((self.dir / INDEX).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for d in raw if isinstance(raw, list) else []:
            try:
                e = HistoryEntry(name=str(d["name"]), file=str(d["file"]), sent_at=float(d["sent_at"]),
                                 summary=str(d.get("summary", "")), lines=int(d.get("lines", 0)))
            except (KeyError, TypeError, ValueError):
                continue
            if (self.dir / e.file).is_file():
                out.append(e)
        return out

    def _write(self, entries: list[HistoryEntry]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (INDEX + ".tmp")
        tmp.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.dir / INDEX)

    # ------------------------------------------------------------ API
    def record(self, name: str, gcode: str, summary: str = "", now: float | None = None) -> HistoryEntry:
        """Auftrag ablegen (neuester zuerst) und Überzählige löschen."""
        now = time.time() if now is None else now
        self.dir.mkdir(parents=True, exist_ok=True)
        base = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "_" + _safe(name)
        file, n = base, 1
        while (self.dir / file).exists():
            n += 1
            file = base.replace("_", f"-{n}_", 1)
        (self.dir / file).write_text(gcode, encoding="utf-8", newline="\n")
        entry = HistoryEntry(name=Path(name).name, file=file, sent_at=now, summary=summary,
                             lines=gcode.count("\n") + (0 if gcode.endswith("\n") else 1))
        entries = [entry] + self.entries()
        keep, drop = entries[:self.max_entries], entries[self.max_entries:]
        for e in drop:
            try:
                (self.dir / e.file).unlink()
            except OSError:
                pass
        self._write(keep)
        return entry

    def load(self, entry: HistoryEntry) -> str:
        return (self.dir / entry.file).read_text(encoding="utf-8")

    def remove(self, entry: HistoryEntry) -> None:
        self._write([e for e in self.entries() if e.file != entry.file])
        try:
            (self.dir / entry.file).unlink()
        except OSError:
            pass

    def clear(self) -> None:
        for e in self.entries():
            self.remove(e)
