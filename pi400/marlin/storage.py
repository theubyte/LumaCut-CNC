"""Files on the Pi's SD card: survive a power cut, a full disk and damage.

Everything the service keeps goes through atomic_write (readers see the old or
the new file, never half of one). A file that cannot be read any more is kept
next to the original as <name>.corrupt, so the next save does not destroy what
is left of it, and the service starts with safe defaults.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

LOG = logging.getLogger("lumacut.storage")

# Large uploads are refused below this much free space (web.py), so settings,
# calibrations and the last head height can still be saved on a nearly full card.
RESERVE_BYTES = 100 * 1024 * 1024
_TEMP_SUFFIX = ".tmp"


def atomic_write(path, data, mode: int = 0o644) -> None:
    """Write ``data`` (text or bytes) so that a crash leaves the old or the new file.

    A unique temporary name: two threads saving at once cannot overwrite each
    other's half-written file. On failure (disk full) no temporary file stays.
    """
    path = Path(path)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=_TEMP_SUFFIX, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return                 # Windows: directories cannot be opened (tests only)
    try:
        os.fsync(dir_fd)       # the rename itself must survive a power cut too
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def quarantine(path) -> None:
    """Keep a damaged file as <name>.corrupt instead of overwriting it later."""
    path = Path(path)
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
        LOG.error("%s beschädigt: als %s.corrupt aufgehoben, Standardwerte aktiv", path, path.name)
    except OSError:
        LOG.exception("%s beschädigt und nicht verschiebbar", path)


def read_json_object(path) -> dict | None:
    """The JSON object in ``path``; None if missing or damaged (then quarantined)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return None
    except OSError:
        LOG.exception("%s nicht lesbar", path)
        return None
    except ValueError:
        pass
    quarantine(path)
    return None


def remove_stale_temp(folder) -> int:
    """Temporary files a power cut left behind (start of the service only)."""
    removed = 0
    for pattern in ("." + "*" + _TEMP_SUFFIX, "*.partial"):
        for path in Path(folder).glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError:
                LOG.warning("Temporäre Datei %s nicht löschbar", path)
    return removed


def free_bytes(path) -> int:
    return shutil.disk_usage(str(path)).free
