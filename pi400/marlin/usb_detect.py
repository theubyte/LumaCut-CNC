"""Discover and verify the actual SKR USB serial device after firmware change.

The ttyACM number can change after a reset or firmware update.
Never guess and persist a /dev/ttyACM* path without first confirming that
the device replies to native M115 and identifies itself as LumaCut Marlin.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .transport import MarlinTransport


def port_candidates(configured: str, device_root: Path = Path("/dev")) -> list[str]:
    """Prefer the configured port if it still exists; probe only serial TTYs."""
    choices: list[str] = []
    if configured and Path(configured).exists():
        choices.append(configured)
    by_id = device_root / "serial" / "by-id"
    if by_id.is_dir():
        choices.extend(str(p) for p in sorted(by_id.iterdir()) if p.exists())
    for glob in ("ttyACM*", "ttyUSB*"):
        choices.extend(str(p) for p in sorted(device_root.glob(glob)))
    seen: set[str] = set()
    ordered: list[str] = []
    for port in choices:
        if port not in seen:
            ordered.append(port)
            seen.add(port)
    return ordered


def locate_verified_marlin(configured: str, device_root: Path = Path("/dev"),
                           factory=MarlinTransport) -> str:
    candidates = port_candidates(configured, device_root=device_root)
    if not candidates:
        raise RuntimeError(
            "Kein serielles SKR USB-Geraet gefunden: /dev/serial/by-id/, "
            "/dev/ttyACM* und /dev/ttyUSB* leer. SKR-Versorgung, "
            "USB-Datenkabel, dmesg und Firmware/Bootloader pruefen.")
    for path in candidates:
        device = factory(path)
        try:
            device.ensure_ready()  # Native M115 and LumaCut identity required.
            print(f"Marlin LumaCut SKR erkannt: {path}", file=sys.stderr)
            return path
        except Exception as exc:
            print(f"USB-Kandidat {path}: {exc}", file=sys.stderr)
        finally:
            with device.lock:
                device._close_locked()
    raise RuntimeError(
        "Ein serielles USB-Geraet ist sichtbar, aber keine LumaCut-Marlin-"
        "Firmware wurde anhand von M115 bestaetigt. Falsche Firmware? "
        "LumaCut-Marlin-Firmware einmalig per SD-Karte flashen.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("configured_port", help="previous LUMACUT_SKR path")
    args = parser.parse_args()
    try:
        found = locate_verified_marlin(args.configured_port)
        print(found)  # stdout ONLY selected verified device path
    except Exception as exc:
        print("LumaCut Marlin USB: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
