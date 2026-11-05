"""SKR firmware update over USB: the firmware's self-update (M997).

docs/FIRMWARE_EIGEN.md, Selbst-Update::

    Pi:  M997 U<bytes> C<crc32>     SKR: ok READY <chunk>
    Pi:  <chunk> raw bytes          SKR: ok <offset>      (repeated)
                                    SKR: ok DONE          (image checked)

The firmware stores the image in upper flash and copies it to 0x08007000 only
after the checksum and the identification were good. Everything before
"ok DONE" leaves the running firmware untouched. The BTT bootloader is never
touched; the SD card stays the way back.
"""
from __future__ import annotations

import re
import struct
import time
import zlib

# SKR Mini MZ with STM32F103RET6: 512 KB flash, 64 KB RAM. The BTT bootloader
# occupies the first 28 KB and starts the application at 0x08007000. The
# firmware takes at most 196 KB (contract), the upper flash holds the download.
APP_BASE = 0x08007000
MAX_IMAGE = 196 * 1024
MIN_IMAGE = 4 * 1024
FLASH_END = APP_BASE + MAX_IMAGE
SRAM_BASE, SRAM_END = 0x20000000, 0x20010000
IDENTITY = b"LumaCut CNC"
SELF_UPDATE = b"Cap:SELF_UPDATE:1"


class FirmwareImageError(ValueError):
    """The uploaded file is not a flashable LumaCut SKR image."""


class TransferError(RuntimeError):
    """The transfer to the SKR failed; its running firmware is untouched."""


def build_stamp(image: bytes):
    """Return 'Mon DD YYYY HH:MM:SS' compiled into the image, if present.

    M115 prints the same __DATE__/__TIME__ in parentheses, which lets the Pi
    prove that the SKR really runs the uploaded build.
    """
    date = re.search(rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{4}", image)
    clock = re.search(rb"(?<![\d:])\d\d:\d\d:\d\d(?![\d:])", image)
    if not date or not clock:
        return None
    return date.group(0).decode() + " " + clock.group(0).decode()


def validate_image(image: bytes) -> dict:
    """Refuse anything that would not boot, or that cannot be updated again."""
    if not MIN_IMAGE <= len(image) <= MAX_IMAGE:
        raise FirmwareImageError(
            f"Dateigröße {len(image)} Byte unplausibel (erlaubt {MIN_IMAGE // 1024} KB bis {MAX_IMAGE // 1024} KB)")
    stack, reset = struct.unpack_from("<II", image, 0)
    if not (SRAM_BASE < stack <= SRAM_END and APP_BASE <= (reset & ~1) < FLASH_END):
        raise FirmwareImageError(
            "Keine SKR-Mini-MZ-Firmware für den BTT-Bootloader (Startadresse 0x08007000)")
    if IDENTITY not in image:
        raise FirmwareImageError("LumaCut-Kennung fehlt: fremde Firmware wird nicht geflasht")
    if SELF_UPDATE not in image:
        # Also refuses every LumaCut Marlin build. Without M997 the next update needs the SD card.
        raise FirmwareImageError(
            "Firmware ohne Selbst-Update (Cap:SELF_UPDATE:1): Marlin-Abbild oder danach "
            "kein Update über den Pi mehr möglich")
    return {"bytes": len(image), "build": build_stamp(image)}


def update_command(image: bytes) -> str:
    """M997 line for ``image``: size and CRC-32 (zlib/IEEE 802.3), both decimal."""
    return "M997 U%d C%d" % (len(image), zlib.crc32(image) & 0xFFFFFFFF)


class SelfUpdateUploader:
    """Device dialogue of M997 over an already open, idle pyserial port."""

    def __init__(self, serial, log=None, block_timeout: float = 10.0, done_timeout: float = 30.0):
        self.serial = serial
        self.log = log or (lambda line: None)
        self.block_timeout = block_timeout
        self.done_timeout = done_timeout

    def _answer(self, pattern: str, timeout: float) -> re.Match:
        """Next line matching ``pattern``; an Error: line ends the transfer."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self.serial.readline()
            line = raw.decode("utf-8", errors="replace").strip() if raw else ""
            if not line:
                continue
            self.log(line)
            if line.startswith("Error:"):
                raise TransferError("SKR lehnt das Update ab: " + line[:120])
            match = re.match(pattern, line)
            if match:
                return match
        raise TransferError("SKR antwortet nicht während des Firmware-Updates")

    def upload(self, image: bytes, progress=None):
        self.serial.write((update_command(image) + "\n").encode("ascii"))
        chunk = int(self._answer(r"^ok READY (\d+)$", self.block_timeout).group(1))
        if not 16 <= chunk <= 64 * 1024:
            raise TransferError("SKR meldet unbrauchbare Blockgröße %d" % chunk)
        sent = 0
        done = False
        while sent < len(image):
            block = image[sent:sent + chunk]
            self.serial.write(block)
            sent += len(block)
            answer = self._answer(r"^ok (\d+|DONE)$", self.block_timeout).group(1)
            if answer == "DONE":
                if sent != len(image):
                    raise TransferError("SKR meldet DONE bei Byte %d von %d" % (sent, len(image)))
                done = True
            elif int(answer) != sent:
                raise TransferError("SKR bestätigt Byte %s statt %d" % (answer, sent))
            if progress:
                progress(sent, len(image))
        if not done:
            # checksum and identification of the stored image
            self._answer(r"^ok DONE$", self.done_timeout)
