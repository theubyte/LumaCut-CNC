"""Head camera capture (UVC via V4L2) with fixed exposure for the scan.

Auto exposure and auto white balance make every scan tile a little
brighter or darker than its neighbour, so the mosaic shows its seams. The
tablet's light calibration finds fixed values once; they are stored in the
Pi config ("camera") and applied before every snapshot. None = automatic.

Snapshots are taken in MJPEG whenever the camera offers the size that way:
raw YUYV over USB 2.0 only reaches 640 x 480 on most webcams (the OV2710
in the HBVCAM F1716 delivers Full HD only as MJPEG, and at 30 fps not even
that through the Pi 400 hub, hence 15 fps).
"""
from __future__ import annotations

import re
import subprocess
import threading

# value ranges the tablet may set; the camera clamps to its own range too
LIMITS = {"exposure": (1, 10000), "gain": (0, 255), "white_balance": (2000, 10000), "light": (1, 100)}
DEFAULTS = {"exposure": None, "gain": None, "white_balance": None, "light": None}

_lock = threading.Lock()
_formats: dict[str, dict[tuple[int, int], str]] = {}
_ranges: dict[str, dict[str, tuple[int, int]]] = {}
# settings key -> V4L2 control that carries it
CONTROLS = {"exposure": "exposure_time_absolute", "gain": "gain", "white_balance": "white_balance_temperature"}


def validate(data) -> dict:
    """Camera settings from the tablet: each key None (automatic) or an int in LIMITS."""
    if not isinstance(data, dict):
        raise ValueError("Kamera-Einstellungen: JSON-Objekt erwartet")
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ValueError("Unbekannte Kamera-Einstellung: " + ", ".join(sorted(unknown)))
    out = dict(DEFAULTS)
    for key, (low, high) in LIMITS.items():
        v = data.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not low <= v <= high:
            raise ValueError("%s: ganze Zahl %d … %d oder null erwartet" % (key, low, high))
        out[key] = int(v)
    return out


def parse_controls(text: str) -> dict[str, tuple[int, int]]:
    """Control name -> (min, max) from `v4l2-ctl --list-ctrls`."""
    out = {}
    for m in re.finditer(r"^\s*(\w+) 0x[0-9a-f]+ \(int\)\s*: min=(-?\d+) max=(-?\d+)", text, re.M):
        out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


def ranges(device: str) -> dict[str, tuple[int, int]]:
    """Settings key -> (min, max) the camera itself accepts (empty when unknown)."""
    if device not in _ranges:
        try:
            done = subprocess.run(["v4l2-ctl", "-d", device, "--list-ctrls"],
                                  capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        found = parse_controls(done.stdout)
        _ranges[device] = {key: found[ctl] for key, ctl in CONTROLS.items() if ctl in found}
    return _ranges[device]


def control_steps(settings: dict, limits: dict | None = None) -> list[list[str]]:
    """v4l2-ctl -c arguments in two steps: the auto switches first, then the
    values (a manual value is refused while its automatic is still on).
    Values are clamped to the camera's own [limits]."""
    def clamp(key):
        v = settings.get(key)
        if v is None or not limits or key not in limits:
            return v
        return min(max(v, limits[key][0]), limits[key][1])
    exposure = clamp("exposure"); wb = clamp("white_balance"); gain = clamp("gain")
    modes = ["auto_exposure=%d" % (3 if exposure is None else 1),
             "white_balance_automatic=%d" % (1 if wb is None else 0)]
    if exposure is not None:
        modes.append("exposure_dynamic_framerate=0")
    values = []
    if exposure is not None:
        values.append("exposure_time_absolute=%d" % exposure)
    if wb is not None:
        values.append("white_balance_temperature=%d" % wb)
    if gain is not None:
        values.append("gain=%d" % gain)
    return [modes] + ([values] if values else [])


def parse_formats(text: str) -> dict[tuple[int, int], str]:
    """Size -> best pixel format from `v4l2-ctl --list-formats-ext` (MJPEG preferred)."""
    out: dict[tuple[int, int], str] = {}
    fmt = None
    for line in text.splitlines():
        m = re.search(r"\[\d+\]: '(\w+)'", line)
        if m:
            fmt = m.group(1)
            continue
        m = re.search(r"Size: Discrete (\d+)x(\d+)", line)
        if m and fmt:
            size = (int(m.group(1)), int(m.group(2)))
            if out.get(size) != "MJPG":
                out[size] = fmt
    return out


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first SOF marker of a JPEG, None if not found."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return (data[i + 7] << 8 | data[i + 8], data[i + 5] << 8 | data[i + 6])
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + (data[i + 2] << 8 | data[i + 3])
    return None


def ffmpeg_command(device: str, width: int, height: int, fmt: str | None, skip: int) -> list[str]:
    # loglevel info: the "Stream #0" line tells that the camera is streaming
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostats", "-f", "v4l2"]
    if fmt == "MJPG":
        cmd += ["-input_format", "mjpeg", "-framerate", "15"]
    cmd += ["-video_size", "%dx%d" % (width, height), "-i", device,
            "-vf", r"select=gte(n\,%d)" % skip, "-frames:v", "1", "-q:v", "2", "-f", "image2", "pipe:1"]
    return cmd


def formats(device: str) -> dict[tuple[int, int], str]:
    if device not in _formats:
        done = subprocess.run(["v4l2-ctl", "-d", device, "--list-formats-ext"],
                              capture_output=True, text=True, timeout=10, check=False)
        found = parse_formats(done.stdout)
        if found:
            _formats[device] = found
        return found
    return _formats[device]


def _set_controls(device: str, settings: dict) -> None:
    for args in control_steps(settings, ranges(device)):
        subprocess.run(["v4l2-ctl", "-d", device] + [a for c in args for a in ("-c", c)],
                       capture_output=True, timeout=10, check=False)


def snapshot(device: str, width: int, height: int, settings: dict) -> bytes:
    """One JPEG of exactly width x height with [settings] applied; raises if the camera cannot.

    UVC cameras like the OV2710 set the exposure time to the frame period
    when streaming starts, so the controls are set again once ffmpeg reports
    the stream, and the frames before they take effect are skipped.
    """
    with _lock:   # one capture at a time: a second open would fail with "busy"
        sizes = formats(device)
        if sizes and (width, height) not in sizes:
            raise ValueError("Kamera kann %d × %d nicht (möglich: %s)" % (
                width, height, ", ".join("%d × %d" % s for s in sorted(sizes, reverse=True))))
        try:
            _set_controls(device, settings)
            # 15 fps: about 1 s of frames, the controls are set again after the first ones
            skip = 14 if settings.get("exposure") is not None else 8
            proc = subprocess.Popen(ffmpeg_command(device, width, height, sizes.get((width, height)), skip),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            killer = threading.Timer(20, proc.kill)
            killer.start()
            try:
                log = []
                for raw in proc.stderr:
                    line = raw.decode("utf-8", "replace")
                    log.append(line)
                    if "Stream #0" in line:
                        _set_controls(device, settings)
                        break
                out, rest = proc.communicate()
                log.append(rest.decode("utf-8", "replace"))
            finally:
                killer.cancel()
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectionError("Kamera antwortet nicht: " + str(exc)[:120])
    if proc.returncode != 0 or not out.startswith(b"\xff\xd8"):
        errors = [l.strip() for l in log if "rror" in l or "busy" in l.lower()] or ["".join(log).strip()[-160:]]
        raise ConnectionError("Kamera lieferte kein Bild: " + " ".join(errors)[:160])
    got = jpeg_size(out)
    if got is not None and got != (width, height):
        raise ValueError("Kamera lieferte %d × %d statt %d × %d" % (got + (width, height)))
    return out
