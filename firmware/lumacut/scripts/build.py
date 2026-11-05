#!/usr/bin/env python3
"""Builds the LumaCut firmware, checks the image, writes firmware.bin + manifest.json.

Does not write to a board, USB or SD. Same manifest layout as firmware/marlin/build.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = "skr_mini_mz"
APP_ADDR = 0x08007000
MAX_BYTES = 196 * 1024


def objdump() -> pathlib.Path:
    core = pathlib.Path(os.environ.get("PLATFORMIO_CORE_DIR", pathlib.Path.home() / ".platformio"))
    pinned = re.search(r"toolchain-gccarmnoneeabi@([\d.]+)", (ROOT / "platformio.ini").read_text()).group(1)
    for folder in sorted((core / "packages").glob("toolchain-gccarmnoneeabi*")):
        package = folder / "package.json"
        if package.is_file() and json.loads(package.read_text())["version"] == pinned:
            for name in ("arm-none-eabi-objdump.exe", "arm-none-eabi-objdump"):
                tool = folder / "bin" / name
                if tool.is_file():
                    return tool
    raise RuntimeError("objdump of toolchain " + pinned + " not found")


def check_image(data: bytes, version: str) -> None:
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"image {len(data)} bytes, limit {MAX_BYTES}")
    sp, reset = struct.unpack("<II", data[:8])
    if not 0x20000000 <= sp <= 0x20010000:
        raise RuntimeError(f"bad stack pointer {sp:#x}")
    if not (reset & 1 and APP_ADDR <= reset < APP_ADDR + len(data)):
        raise RuntimeError(f"bad reset vector {reset:#x}")
    if b"LumaCut CNC" not in data or version.encode() not in data:
        raise RuntimeError("LumaCut id or version missing in the image")


def main() -> int:
    version = re.search(r'LUMACUT_VERSION "([^"]+)"', (ROOT / "version.h").read_text()).group(1)
    subprocess.run([sys.executable, "-m", "platformio", "run", "-d", str(ROOT), "-e", ENV], check=True)
    build = ROOT / ".pio" / "build" / ENV
    subprocess.run([sys.executable, str(ROOT / "scripts" / "check_ramfunc.py"), str(objdump()),
                    str(build / "firmware.elf")], check=True)
    data = (build / "firmware.bin").read_bytes()
    check_image(data, version)
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    shutil.copyfile(build / "firmware.bin", out / "firmware.bin")
    details = {
        "project": "LumaCut CNC firmware",
        "version": version,
        "board": "BOARD_BTT_SKR_MINI_MZ_V1_0",
        "environment": ENV,
        "cpu": "STM32F103RET6",
        "usb": "libopencm3 USB CDC",
        "laser": {"supply": "FAN1 PC6 M106-M107 (Pi 180s cooldown)", "pwm": "PA9 EXP3 (TIM1 CH2, 1 kHz, hardware)",
                  "mode": "M3 I", "s_max": 255},
        "accessories": {"lights": "M355 S<0|1> P<0-255> HE0 PC8 (TIM8 CH3 PWM)",
                        "exhaust": "M8 BED PC9"},
        "tones": "M300 S<Hz> P<ms> [X] [Y]: stepper coils, no motion, laser must be off",
        "update": "M997 U<bytes> C<crc32>, stage 0x08040000, copied by a RAM routine; SD rescue stays",
        "input_shaping": "none",
        "size": len(data),
        "hardware_verified": False,
        "do_not_flash_before_isolation_interlock_test": True,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    (out / "manifest.json").write_text(json.dumps(details, indent=2) + "\n")
    print("LumaCut image:", out / "firmware.bin", len(data), "bytes, sha256", details["sha256"])
    print("NOT VERIFIED ON THE MACHINE: no release, not for real-laser use yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
