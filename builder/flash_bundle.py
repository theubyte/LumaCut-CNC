"""Create an ESP32-S3 complete image and an offline-capable local flash launcher.

Only the Waveshare HMI is eligible. The build server never accesses a serial
device: flashing happens from a secure browser page or on localhost.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import zipfile

IMAGE_NAME = "LUMACUT_HMI_ESP32S3_MERGED.bin"
LOCAL_IMAGE_NAME = "firmware.bin"
FLASH_OFFSET = 0
FLASH_LIMIT = 16 * 1024 * 1024


def find_boot_app0(core: Path) -> Path:
    packages = core / "packages"
    preferred = packages / "framework-arduinoespressif32" / "tools" / "partitions" / "boot_app0.bin"
    if preferred.is_file():
        return preferred
    matches = sorted(packages.glob("framework-arduinoespressif32*/tools/partitions/boot_app0.bin"))
    if not matches:
        # Variants of pioarduino/framework packages can place the file deeper.
        matches = sorted(packages.glob("framework-arduinoespressif32*/**/boot_app0.bin"))
    if not matches:
        raise RuntimeError("PlatformIO boot_app0.bin nicht gefunden; kein Flash-Paket erzeugt")
    return matches[0]


def flash_manifest(image_path: str, version: str) -> dict:
    return {
        "name": "LumaCut Waveshare HMI (Laborversion)",
        "version": version,
        "new_install_prompt_erase": False,
        "builds": [
            {"chipFamily": "ESP32-S3",
             "parts": [{"path": image_path, "offset": FLASH_OFFSET}]}
        ],
    }


def build_flash_package(output: Path, folder: Path, source_sha: str, profile: str,
                        templates: Path, core: Path | None = None) -> list[dict]:
    """Assemble/validate entire 16 MB ESP32-S3 flash layout; generate localhost ZIP.

    This does NOT verify real hardware functionality, electrical compatibility,
    motor safety, or a successful flash.
    """
    core = core or Path(os.environ.get("PLATFORMIO_CORE_DIR", "/data/pio"))
    required = {
        "bootloader": output / "bootloader.bin",
        "partitions": output / "partitions.bin",
        "application": output / "firmware.bin",
    }
    for name, filename in required.items():
        if not filename.is_file() or filename.stat().st_size == 0:
            raise RuntimeError(f"{name} fehlt: {filename}")
    boot_app0 = find_boot_app0(core)
    parts = [
        (0x0, required["bootloader"]),
        (0x8000, required["partitions"]),
        (0xe000, boot_app0),
        (0x10000, required["application"]),
    ]
    for i, (offset, filename) in enumerate(parts):
        boundary = parts[i + 1][0] if i + 1 < len(parts) else FLASH_LIMIT
        if offset + filename.stat().st_size > boundary:
            raise RuntimeError(f"Image-Überlappung oder zu groß: {filename.name}")
    merged = folder / IMAGE_NAME
    subprocess.run([
        sys.executable, "-m", "esptool", "--chip", "esp32s3", "merge_bin",
        "-o", str(merged), "--flash_mode", "dio", "--flash_freq", "40m",
        "--flash_size", "16MB",
        *[value for offset, filename in parts for value in (hex(offset), str(filename))],
    ], check=True, timeout=180)
    if not merged.is_file() or not (0x10000 < merged.stat().st_size <= FLASH_LIMIT):
        raise RuntimeError("Ungültige Größe des kombinierten ESP32-S3-Images")
    with merged.open("rb") as f:
        if f.read(1) != b"\xe9":
            raise RuntimeError("Bootloader-Image hat kein ESP-Image-Magic")
    version = f"{source_sha[:12]}-{profile}"
    local_manifest = flash_manifest(LOCAL_IMAGE_NAME, version)
    web_manifest = flash_manifest(IMAGE_NAME, version)
    # Published manifest gets the job-scoped path from the authenticated API.
    (folder / "flash-manifest.json").write_text(json.dumps(web_manifest, indent=2), encoding="utf-8")
    bundle = folder / "Waveshare-HMI-Flash-Paket-Windows.zip"
    launcher = """@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 flash_local.py
) else (
  python flash_local.py
)
if errorlevel 1 (
  echo Python 3 fehlt oder konnte nicht gestartet werden.
  echo Python von https://www.python.org/downloads/ installieren.
  pause
)
"""
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(merged, LOCAL_IMAGE_NAME)
        z.writestr("manifest.json", json.dumps(local_manifest, indent=2))
        z.writestr("Flash-Waveshare-Windows.cmd", launcher)
        z.write(templates / "flash_local.py", "flash_local.py")
        z.write(templates / "flash_ui.html", "flash_ui.html")
        z.writestr("BITTE-LESEN.txt",
                   "LumaCut HMI Laborversion: Flashen per USB am Windows-PC.\\n"
                   "1. ZIP entpacken, 2. USB TO UART verbinden, UART1 einstellen,\\n"
                   "3. Flash-Waveshare-Windows.cmd starten, 4. Chrome/Edge nutzen.\\n"
                   "Python 3 benoetigt; das Browser-Flashmodul benoetigt Internet.\\n"
                   "Nur fuer Waveshare ESP32-S3-Touch-LCD-7 Rev1.2!\\n"
                   "Dies ist eine ungepruefte Entwicklungsfirmware.\\n"
                   "Laser waehrend der Inbetriebnahme physisch stromlos lassen.\\n")
    return [
        file_meta(merged),
        file_meta(bundle),
    ]


def file_meta(path: Path) -> dict:
    digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest}
