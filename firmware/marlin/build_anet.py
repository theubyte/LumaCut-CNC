#!/usr/bin/env python3
"""LumaCut Marlin for the Anet V1.0/V1.7 board (ATmega1284P), stand-in with Z.

Emergency option since the SKR Mini MZ died (31.10.2026): the Anet board
has a Z driver, the Atomstack board does not. Same Marlin 2.1.2.9 and the
same LumaCut behaviour as build.py, from the official Anet A8 example.
Does not write to an attached board; flashing is a separate step with the
owner present (avrdude -c arduino -b 115200, Optiboot answers on USB).

Wiring this build expects (docs/STAND.md):
  - board on the 24 V supply (its stock A8 supply was 24 V); laser on the
    LaserTree adapter at the same 24 V; TTL from ISP header MISO = D6/PB6 (Timer3 hardware PWM, ~2.5 kHz)
    and ISP GND, with a 10 kOhm pull-down TTL->GND so the laser stays dark
    while the chip is in reset or in the boot loader (pin floats then)
  - X/Y/Z motors and min switches on the stock connectors
  - FAN connector (D4, 24 V low-side) switches a 24 V relay coil whose
    contact switches the laser's +24 V: M106 P0 S255 / M107 P0, as the Pi
    does on the SKR (high side, so the laser GND never floats against TTL)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import tempfile

import build
from build import disable_active, replace_active, run, uncomment

ROOT = build.ROOT
VERSION = build.VERSION
EXAMPLE = "config/examples/Anet/A8"
PIO_ENV = "sanguino1284p_optimized"
BOARD = "BOARD_ANET_10"
# Optiboot on the board answers at 115200; Marlin itself runs at 250000:
# exact on a 16 MHz AVR (115200 is 2.1 % off) and twice the line rate for
# grey-scale fills.
BAUD = "250000"


def patch_configuration(cfg: str, adv: str) -> tuple[str, str]:
    cfg = replace_active(cfg, "BAUDRATE", BAUD)
    cfg = replace_active(cfg, "CUSTOM_MACHINE_NAME", '"LumaCut CNC Marlin Anet"')
    cfg = cfg.replace('#define STRING_CONFIG_H_AUTHOR "(MarlinFirmware)"',
                      '#define STRING_CONFIG_H_AUTHOR "(LumaCut CNC Anet stand-in)"')
    # No hotend, no bed heater, no thermistors: a laser.
    cfg = replace_active(cfg, "EXTRUDERS", "0")
    cfg = replace_active(cfg, "TEMP_SENSOR_0", "0")
    cfg = replace_active(cfg, "TEMP_SENSOR_BED", "0")
    for name in ("PIDTEMP", "PIDTEMPBED", "PREVENT_COLD_EXTRUSION",
                 "THERMAL_PROTECTION_HOTENDS", "THERMAL_PROTECTION_BED",
                 "THERMAL_PROTECTION_CHAMBER", "THERMAL_PROTECTION_COOLER"):
        cfg = disable_active(cfg, name)
    # Headless: the Pi is the user interface; no LCD, no SD (SPI pins free,
    # MISO carries the laser PWM).
    for name in ("ZONESTAR_LCD", "SDSUPPORT", "SHOW_BOOTSCREEN"):
        cfg = disable_active(cfg, name)
    # Same axes, switches and probing as the SKR build (build.py).
    cfg = replace_active(cfg, "X_MIN_ENDSTOP_INVERTING", "true")
    cfg = replace_active(cfg, "Y_MIN_ENDSTOP_INVERTING", "true")
    cfg = replace_active(cfg, "Z_MIN_ENDSTOP_INVERTING", "true")
    cfg = replace_active(cfg, "Z_MIN_PROBE_ENDSTOP_INVERTING", "true")
    cfg = replace_active(cfg, "INVERT_X_DIR", "false")
    cfg = replace_active(cfg, "INVERT_Y_DIR", "false")
    cfg = replace_active(cfg, "INVERT_Z_DIR", "false")
    cfg = replace_active(cfg, "X_BED_SIZE", "390")
    cfg = replace_active(cfg, "Y_BED_SIZE", "370")
    cfg = replace_active(cfg, "X_MIN_POS", "0")
    cfg = replace_active(cfg, "Y_MIN_POS", "0")
    cfg = replace_active(cfg, "Z_MAX_POS", "80")
    probe_directive = "Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN"
    if not re.search(r"(?m)^\s*#define\s+" + probe_directive + r"(?:\s|$)", cfg):
        cfg = re.sub(r"(?m)^(\s*)//\s*(#define\s+" + probe_directive + r")", r"\1\2", cfg, count=1)
    cfg = uncomment(cfg, "FIX_MOUNTED_PROBE")
    cfg = uncomment(cfg, "Z_SAFE_HOMING")
    cfg = replace_active(cfg, "Z_SAFE_HOMING_X_POINT", "0")
    cfg = replace_active(cfg, "Z_SAFE_HOMING_Y_POINT", "0")
    cfg = replace_active(cfg, "NOZZLE_TO_PROBE_OFFSET", "{ 0, 0, 0 }")
    cfg = replace_active(cfg, "Z_PROBE_LOW_POINT", "-2")
    cfg = replace_active(cfg, "Z_CLEARANCE_MULTI_PROBE", "16")
    cfg = replace_active(cfg, "Z_CLEARANCE_BETWEEN_PROBES", "16")
    # A5 Pro belts 80 steps/mm, head v6 Z rack 80 steps/mm (A4988, 1/16).
    cfg = replace_active(cfg, "DEFAULT_AXIS_STEPS_PER_UNIT", "{ 80, 80, 80 }")
    cfg = replace_active(cfg, "HOMING_FEEDRATE_MM_M", "{ (50*60), (50*60), 432 }")
    cfg = replace_active(cfg, "Z_PROBE_FEEDRATE_FAST", "432")
    cfg = replace_active(cfg, "Z_PROBE_FEEDRATE_SLOW", "216")
    # Motors on 12 V (not 24 V as on the SKR): less torque at speed. Same
    # 150 mm/s cap; the Pi's motion calibration sets the real limits.
    cfg = replace_active(cfg, "DEFAULT_MAX_FEEDRATE", "{ 150, 150, 9 }")
    cfg = replace_active(cfg, "DEFAULT_MAX_ACCELERATION", "{ 500, 500, 100 }")
    cfg = replace_active(cfg, "DEFAULT_ACCELERATION", "500")
    cfg = replace_active(cfg, "DEFAULT_TRAVEL_ACCELERATION", "500")

    adv = replace_active(adv, "AXIS_RELATIVE_MODES", "{ false, false, false }")
    adv = uncomment(adv, "LASER_FEATURE")
    adv = replace_active(adv, "SPINDLE_LASER_ACTIVE_STATE", "HIGH")
    adv = replace_active(adv, "CUTTER_POWER_UNIT", "PWM255")
    laser_default = "#define SPEED_POWER_STARTUP        80    // (%)"
    if adv.count(laser_default) != 1:
        raise RuntimeError("Marlin laser startup value layout changed")
    adv = adv.replace(laser_default, "#define SPEED_POWER_STARTUP         0    // (%)", 1)
    adv = uncomment(adv, "EMERGENCY_PARSER")
    adv = uncomment(adv, "ADVANCED_OK")
    # Grey-scale fills are many short lines: plenty of RAM left (~2.4 of
    # 16 KB) for a deeper planner, command queue and serial input buffer.
    block = "#else\n  #define BLOCK_BUFFER_SIZE 16\n#endif"
    if adv.count(block) != 1:
        raise RuntimeError("Marlin BLOCK_BUFFER_SIZE layout changed")
    adv = adv.replace(block, "#else\n  #define BLOCK_BUFFER_SIZE 32 // LumaCut headless laser\n#endif", 1)
    adv = replace_active(adv, "BUFSIZE", "16")
    adv = adv.replace("//#define RX_BUFFER_SIZE 1024", "#define RX_BUFFER_SIZE 256", 1)
    return cfg, adv


PIN_PATCH = """
// LumaCut CNC (build_anet.py): headless laser on the Anet V1.0/V1.7.
// Laser TTL: ISP header MISO = D6 = PB6 = OC3A, Timer3 hardware PWM (Marlin
// already runs Timer3 at 1 kHz on the 1284P; Timer0/1/2 are taken).
// Needs a 10k pull-down to GND: the pin floats during reset/boot loader.
#define SPINDLE_LASER_PWM_PIN 6
// Marlin wants an enable pin: the unused hotend thermistor input A7/D24.
// It MUST NOT be wired to anything that powers the laser.
#define SPINDLE_LASER_ENA_PIN 24
#undef TEMP_0_PIN
#define TEMP_0_PIN -1
#undef TEMP_BED_PIN
#define TEMP_BED_PIN -1
#undef HEATER_0_PIN
#define HEATER_0_PIN -1
#undef HEATER_BED_PIN
#define HEATER_BED_PIN -1
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=pathlib.Path, default=ROOT / "dist-anet")
    ap.add_argument("--cache-dir", type=pathlib.Path,
                    default=pathlib.Path.home() / ".cache" / "lumacut" / "upstreams")
    ap.add_argument("--marlin", type=pathlib.Path, help="local Marlin-2.1.2.9 checkout")
    ap.add_argument("--configurations", type=pathlib.Path, help="local Configurations-2.1.2.9 checkout")
    ap.add_argument("--keep", type=pathlib.Path, help="build here instead of a temp dir (debugging)")
    args = ap.parse_args()

    def source(local, name, upstream, ref):
        if local:
            return local
        cache = args.cache_dir.expanduser().resolve()
        cache.mkdir(parents=True, exist_ok=True)
        destination = cache / (name + "-" + VERSION)
        if not destination.exists():
            run("git", "clone", "--depth", "1", "--branch", ref, upstream, str(destination), timeout=500)
        return destination

    marlin_source = source(args.marlin, "Marlin", build.UPSTREAM, VERSION)
    examples_source = source(args.configurations, "Configurations", build.CONFIGS, f"release-{VERSION}")
    with tempfile.TemporaryDirectory(prefix="lumacut-anet-") as base:
        work = args.keep or pathlib.Path(base)
        if args.keep and work.exists():
            shutil.rmtree(work / "Marlin" / "Marlin", ignore_errors=True)
        src = work / "Marlin"
        ignore = shutil.ignore_patterns(".git", ".pio", "__pycache__")
        shutil.copytree(marlin_source, src, ignore=ignore, dirs_exist_ok=True)
        example = examples_source / EXAMPLE
        cfg, adv = patch_configuration((example / "Configuration.h").read_text(),
                                       (example / "Configuration_adv.h").read_text())
        (src / "Marlin" / "Configuration.h").write_text(cfg)
        (src / "Marlin" / "Configuration_adv.h").write_text(adv)
        pins = src / "Marlin/src/pins/sanguino/pins_ANET_10.h"
        pin_text = pins.read_text()
        if pin_text.count('#define BOARD_INFO_NAME "Anet 1.0"') != 1:
            raise RuntimeError("Official Anet pinout changed")
        pins.write_text(pin_text + PIN_PATCH)
        # Marlin's PWM_PIN list for the 1284P predates its own Timer3 support
        # (HAL/AVR/fast_pwm.cpp handles TIMER3A/B, init_pwm_timers() already
        # sets D6 to 1 kHz, and the sanguino core maps D6/D7 to TIMER3A/B).
        fastio = src / "Marlin/src/HAL/AVR/fastio.h"
        old = "#define PWM_PIN(P)  (P == 3 || P == 4 || P == 14 || P == 15)"
        text = fastio.read_text()
        if text.count(old) != 1:
            raise RuntimeError("Marlin 1284P PWM_PIN list changed")
        fastio.write_text(text.replace(
            old, "#define PWM_PIN(P)  (P == 3 || P == 4 || P == 6 || P == 7 || P == 14 || P == 15) // LumaCut: + Timer3", 1))
        build.patch_motor_tone(src)
        ini = src / "platformio.ini"
        ini.write_text(re.sub(r"(?m)^default_envs\s*=.*$", "default_envs = " + PIO_ENV, ini.read_text(), count=1))
        run("pio", "run", "-e", PIO_ENV, cwd=src, timeout=2100)
        hexes = list((src / ".pio" / "build" / PIO_ENV).glob("firmware.hex"))
        if not hexes:
            raise RuntimeError("Marlin ATmega1284P build produced no .hex image")
        out = args.output
        out.mkdir(parents=True, exist_ok=True)
        fw = out / "firmware.hex"
        shutil.copyfile(hexes[0], fw)
        details = {
            "project": "LumaCut CNC Marlin, Anet V1.0/V1.7 stand-in",
            "version": VERSION,
            "board": BOARD,
            "environment": PIO_ENV,
            "cpu": "ATmega1284P",
            "usb": "CH340, Marlin %s baud; Optiboot upload 115200 (avrdude -c arduino)" % BAUD,
            "laser": {"pwm": "D6 PB6 (ISP MISO), Timer3, 10k pull-down to GND", "enable": "D24 unwired",
                      "supply": "LaserTree adapter on 24 V; relay on FAN D4 (M106 P0 / M107 P0)",
                      "mode": "M3 I", "s_max": 255},
            "power": "board and laser on one 24 V supply; laser +24 V through the FAN D4 relay",
            "tones": "M300 S<Hz> P<ms> [X] [Y]: stepper coils, no motion, laser must be off",
            "hardware_verified": False,
            "sha256": hashlib.sha256(fw.read_bytes()).hexdigest(),
        }
        (out / "manifest.json").write_text(json.dumps(details, indent=2) + "\n")
        print("Anet image created:", fw, "sha256", details["sha256"])
        print("NOT FLASHED. Flash only with the owner at the machine.")


if __name__ == "__main__":
    main()
