#!/usr/bin/env python3
"""Reproducible, separate Marlin SKR Mini MZ laser build.

Clones Marlin 2.1.2.9 and its matching Anycubic/Mega Zero SKR Mini MZ
example configuration. Does not write to an attached board, USB, or SD.
All physical laser power remains disconnected during first tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
VERSION = "2.1.2.9"
UPSTREAM = "https://github.com/MarlinFirmware/Marlin.git"
CONFIGS = "https://github.com/MarlinFirmware/Configurations.git"
EXAMPLE = "config/examples/AnyCubic/Mega Zero/BigTreeTech SKR Mini MZ V1.0"
PIO_ENV = "STM32F103RC_btt_USB_maple"
BOARD = "BOARD_BTT_SKR_MINI_MZ_V1_0"


def replace_active(src: str, name: str, value: str) -> str:
    pattern = re.compile(r"^(\s*#define\s+" + re.escape(name) +
                         r")\s+([^\r\n/]*)([^\r\n]*)$", re.MULTILINE)
    matches = list(pattern.finditer(src))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one active define for {name}: {len(matches)}")
    old = matches[0].group(0)
    return src.replace(old, f"#define {name} {value}", 1)


def uncomment(src: str, directive: str) -> str:
    expected = f"//#define {directive}"
    if src.count(expected) != 1:
        raise RuntimeError(f"Missing inactive feature {directive}")
    return src.replace(expected, f"#define {directive}", 1)


def disable_active(src: str, directive: str) -> str:
    pattern = re.compile(r"^#define\s+" + re.escape(directive) +
                         r"(?:\s|$).*$", re.MULTILINE)
    if len(pattern.findall(src)) != 1:
        raise RuntimeError("Expected active setting: " + directive)
    return pattern.sub(f"//#define {directive} // LumaCut headless", src, count=1)


def patch_configuration(cfg: str, adv: str) -> tuple[str, str]:
    # Headless USB CDC. Keep the stock STM32F103RC 28k bootloader layout.
    # The Mega Zero's second serial output is a hardware UART; it is not
    # required for the Pi 400 USB gateway.
    cfg = replace_active(cfg, "SERIAL_PORT", "-1")
    cfg = replace_active(cfg, "SERIAL_PORT_2", "2")
    cfg = replace_active(cfg, "BAUDRATE", "115200")
    cfg = replace_active(cfg, "CUSTOM_MACHINE_NAME", '"LumaCut CNC Marlin"')
    # LumaCut endstops are active-low / normally-closed in this installation.
    # Stock Mega Zero config reports all three unpressed switches as
    # TRIGGERED. Invert only the three installed MIN inputs (M119 check).
    cfg = replace_active(cfg, "X_MIN_ENDSTOP_INVERTING", "true")
    cfg = replace_active(cfg, "Y_MIN_ENDSTOP_INVERTING", "true")
    cfg = replace_active(cfg, "Z_MIN_ENDSTOP_INVERTING", "true")
    # Verified by physical jogging: stock Mega Zero X/Y motor direction
    # is opposite on LumaCut. Z already moves correctly; leave Z alone.
    cfg = replace_active(cfg, "INVERT_X_DIR", "false")
    cfg = replace_active(cfg, "INVERT_Y_DIR", "false")
    cfg = replace_active(cfg, "INVERT_Z_DIR", "false")
    cfg = replace_active(cfg, "EXTRUDERS", "0")
    cfg = replace_active(cfg, "TEMP_SENSOR_0", "0")
    cfg = replace_active(cfg, "X_BED_SIZE", "390")
    cfg = replace_active(cfg, "Y_BED_SIZE", "370")
    cfg = replace_active(cfg, "X_MIN_POS", "0")
    cfg = replace_active(cfg, "Z_MAX_POS", "90")
    # Native Marlin G30 uses the installed Z-min mechanical contact switch.
    # Unlike G28 it measures height without changing machine Z=0.
    cfg = replace_active(cfg, "Z_MIN_PROBE_ENDSTOP_INVERTING", "true")
    cfg = uncomment(cfg, "FIX_MOUNTED_PROBE")
    cfg = uncomment(cfg, "Z_SAFE_HOMING")
    cfg = replace_active(cfg, "Z_SAFE_HOMING_X_POINT", "0")
    cfg = replace_active(cfg, "Z_SAFE_HOMING_Y_POINT", "0")
    cfg = replace_active(cfg, "NOZZLE_TO_PROBE_OFFSET", "{ 0, 0, 0 }")
    cfg = replace_active(cfg, "Z_PROBE_LOW_POINT", "0")

    cfg = replace_active(cfg, "DEFAULT_AXIS_STEPS_PER_UNIT", "{ 80, 80, 380 }")
    cfg = replace_active(cfg, "DEFAULT_MAX_FEEDRATE", "{ 100, 100, 6 }")
    cfg = replace_active(cfg, "DEFAULT_MAX_ACCELERATION", "{ 500, 500, 100 }")
    cfg = replace_active(cfg, "DEFAULT_ACCELERATION", "500")
    cfg = replace_active(cfg, "DEFAULT_TRAVEL_ACCELERATION", "500")
    cfg = disable_active(cfg, "CR10_STOCKDISPLAY")
    cfg = disable_active(cfg, "SHOW_CUSTOM_BOOTSCREEN")
    cfg = disable_active(cfg, "CUSTOM_STATUS_SCREEN_IMAGE")
    cfg = disable_active(cfg, "LCD_BED_LEVELING")
    cfg = cfg.replace('#define STRING_CONFIG_H_AUTHOR "(MarlinFirmware)"',
                      '#define STRING_CONFIG_H_AUTHOR "(LumaCut CNC experimental Marlin)"')
    # Keep X/Y/Z endstops required. Don't fake probing (Z is not a second probe).
    adv = replace_active(adv, "AXIS_RELATIVE_MODES", "{ false, false, false }")
    adv = uncomment(adv, "LASER_FEATURE")
    adv = replace_active(adv, "SPINDLE_LASER_ACTIVE_STATE", "HIGH")
    adv = replace_active(adv, "CUTTER_POWER_UNIT", "PWM255")
    # Make bare M3 fail-safe at zero rather than Marlin's stock 80% power.
    # The above keyword occurs in both spindle and laser branches. Replace
    # only the *laser* branch after checking a unique exact source token.
    laser_default = "#define SPEED_POWER_STARTUP        80    // (%)"
    if adv.count(laser_default) != 1:
        raise RuntimeError("Marlin laser startup value layout changed")
    adv = adv.replace(laser_default, "#define SPEED_POWER_STARTUP         0    // (%)", 1)
    adv = uncomment(adv, "COOLANT_CONTROL")
    adv = uncomment(adv, "EMERGENCY_PARSER")
    adv = uncomment(adv, "ADVANCED_OK")
    adv = replace_active(adv, "TX_BUFFER_SIZE", "128")
    adv = replace_active(adv, "BUFSIZE", "8")
    adv = adv.replace("//#define RX_BUFFER_SIZE 1024",
                      "#define RX_BUFFER_SIZE 256")
    # No real-time overrides masquerading as GRBL. Marlin M112 is a true stop.
    return cfg, adv


PIN_PATCH = """
// LumaCut CNC laser 24V rail/fan on FAN1 connector, controlled by
// FAN0 firmware output PC6 (M106 P0 S255/M107 P0).
// PC6 is a switched low-side MOSFET, not a 24V source.
// Laser power remains on during post-job cooldown, while PWM PA1 is
// disabled by M5 I. PC7 (unused FAN2 pin) satisfies Marlin laser
// enable; it MUST NOT be wired to a live laser power rail.
// IMPORTANT: this is Pi-mediated cooldown, not hardware-backed.
// Provide a laser-rated independent emergency cutoff / fan after-run
// controller for cooling during controller failure or power loss.
#undef FAN0_PIN
#define FAN0_PIN PC6
#undef FAN1_PIN
#define FAN1_PIN -1
#undef CONTROLLER_FAN_PIN
#define CONTROLLER_FAN_PIN -1
#undef HEATER_0_PIN
#define HEATER_0_PIN -1
#undef HEATER_BED_PIN
#define HEATER_BED_PIN -1
#define SPINDLE_LASER_ENA_PIN PC7
#define SPINDLE_LASER_PWM_PIN PA1
#define COOLANT_MIST_PIN PC8
#define COOLANT_FLOOD_PIN PC9
"""


def run(*argv: str, cwd: pathlib.Path | None = None, timeout: int = 600):
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=cwd, check=True, timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=pathlib.Path,
                    default=ROOT / "dist")
    ap.add_argument("--cache-dir", type=pathlib.Path,
                    default=pathlib.Path.home() / ".cache" / "lumacut" / "upstreams",
                    help="Keep pinned upstream Marlin repositories for faster local builds")
    ap.add_argument("--offline", action="store_true",
                    help="Only use previously cached upstream repositories")
    args = ap.parse_args()

    def clone_once(repo_name: str, upstream: str, ref: str) -> pathlib.Path:
        cache = args.cache_dir.expanduser().resolve()
        cache.mkdir(parents=True, exist_ok=True)
        destination = cache / (repo_name + "-" + VERSION)
        if destination.exists():
            if not (destination / ".git").is_dir():
                raise RuntimeError("Incomplete Marlin cache: " + str(destination))
            return destination
        if args.offline:
            raise RuntimeError("Upstream checkout not cached: " + str(destination))
        run("git", "clone", "--depth", "1", "--branch", ref,
            upstream, str(destination), timeout=500)
        return destination

    marlin_source = clone_once("Marlin", UPSTREAM, VERSION)
    examples_source = clone_once("Configurations", CONFIGS, f"release-{VERSION}")
    with tempfile.TemporaryDirectory(prefix="lumacut-marlin-") as base:
        build = pathlib.Path(base)
        src, examples = build / "Marlin", build / "Configurations"
        ignore = shutil.ignore_patterns(".git", ".pio", "__pycache__")
        shutil.copytree(marlin_source, src, ignore=ignore)
        shutil.copytree(examples_source, examples, ignore=ignore)
        matched = examples / EXAMPLE
        config = (matched / "Configuration.h").read_text()
        adv = (matched / "Configuration_adv.h").read_text()
        config, adv = patch_configuration(config, adv)
        (src / "Marlin" / "Configuration.h").write_text(config)
        (src / "Marlin" / "Configuration_adv.h").write_text(adv)
        pins = src / "Marlin/src/pins/stm32f1/pins_BTT_SKR_MINI_MZ_V1_0.h"
        pin_text = pins.read_text()
        include = '#include "pins_BTT_SKR_MINI_E3_V2_0.h"'
        if pin_text.count(include) != 1:
            raise RuntimeError("Official Marlin board pinout changed")
        pins.write_text(pin_text + PIN_PATCH)
        ini = src / "platformio.ini"
        text = ini.read_text()
        text = re.sub(r"(?m)^default_envs\s*=.*$",
                      "default_envs = " + PIO_ENV, text, count=1)
        ini.write_text(text)
        run("pio", "run", "-e", PIO_ENV, cwd=src, timeout=2100)
        candidates = list((src / ".pio" / "build" / PIO_ENV).glob("*.bin"))
        if not candidates:
            raise RuntimeError("Marlin STM32F103RC build produced no .bin image")
        out = args.output
        out.mkdir(parents=True, exist_ok=True)
        fw = out / "firmware.bin"
        shutil.copyfile(sorted(candidates, key=lambda p: -p.stat().st_size)[0], fw)
        details = {
            "project": "LumaCut CNC experimental Marlin",
            "version": VERSION,
            "board": BOARD,
            "environment": PIO_ENV,
            "cpu": "STM32F103RC",
            "usb": "Marlin native USB CDC",
            "laser": {"supply": "FAN1 PC6 / FAN0 M106-M107 (Pi 180s cooldown)", "enable": "PC7 unwired", "pwm": "PA1",
                      "mode": "M3 I", "s_max": 255},
            "accessories": {"lights": "M7 HE0 PC8",
                            "exhaust": "M8 BED PC9"},
            "hardware_verified": False,
            "do_not_flash_before_isolation_interlock_test": True,
            "sha256": hashlib.sha256(fw.read_bytes()).hexdigest()
        }
        (out / "manifest.json").write_text(
            json.dumps(details, indent=2) + "\n")
        print("EXPERIMENTAL Marlin image created:", fw, "sha256", details["sha256"])
        print("NOT APPROVED FOR REAL-LASER USE WITHOUT ELECTRICAL VALIDATION.")


if __name__ == "__main__":
    main()
