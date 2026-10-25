"""SKR firmware update over USB, without removing the SD card.

Marlin 2.1 BINARY_FILE_TRANSFER ('M28 B1') writes firmware.bin to the SKR's
onboard SD card. M997 then reboots the STM32F1 (HAL: hal.reboot()) and the
BTT bootloader flashes the file, exactly like a manually inserted card.

Packet format implemented from Marlin/src/feature/binary_stream.h (2.1.2.9):
  header  AD B5 | sync u8 | meta u8 (protocol<<4 | type) | size u16 | csum u16
  payload size bytes (only when size > 0)
  footer  csum u16 over header bytes 2..7 and payload (only when size > 0)
All integers little endian, checksums Fletcher-16 (mod 255).
Marlin answers 'ok<sync>' per accepted packet, 'rs<sync>' for a resend,
'ss<sync>,<max payload>,<version>' for SYNC and 'fe<sync>' on fatal errors.
"""
from __future__ import annotations

import re
import struct
import time

HEADER_TOKEN = 0xB5AD
PROTOCOL_CONTROL, PROTOCOL_FILE = 0, 1
CONTROL_SYNC, CONTROL_CLOSE = 1, 2
FILE_QUERY, FILE_OPEN, FILE_CLOSE, FILE_WRITE, FILE_ABORT = 0, 1, 2, 3, 4

# SKR Mini MZ: 256 KB flash, BTT bootloader occupies the first 28 KB and
# starts the application at 0x08007000.
APP_BASE = 0x08007000
FLASH_END = 0x08040000
MAX_IMAGE = FLASH_END - APP_BASE
SRAM_BASE, SRAM_END = 0x20000000, 0x2000C000
TARGET_NAME = "firmware.bin"


class FirmwareImageError(ValueError):
    """The uploaded file is not a flashable LumaCut SKR image."""


class TransferError(RuntimeError):
    """The binary transfer to the SKR SD card failed."""


def fletcher16(data: bytes, cs: int = 0) -> int:
    for value in data:
        low = ((cs & 0xFF) + value) % 255
        cs = ((((cs >> 8) + low) % 255) << 8) | low
    return cs


def build_packet(sync: int, protocol: int, ptype: int, payload: bytes = b"") -> bytes:
    head = struct.pack("<BBH", sync & 0xFF, (protocol << 4) | ptype, len(payload))
    header_cs = fletcher16(head)
    head += struct.pack("<H", header_cs)
    packet = struct.pack("<H", HEADER_TOKEN) + head
    if payload:
        packet += payload + struct.pack("<H", fletcher16(payload, fletcher16(head)))
    return packet


def build_stamp(image: bytes):
    """Return 'Mon DD YYYY HH:MM:SS' compiled into the image, if present.

    Marlin's M115 prints the same __DATE__/__TIME__ in parentheses, which
    lets the Pi prove that the SKR really runs the uploaded build.
    """
    date = re.search(rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{4}", image)
    clock = re.search(rb"(?<![\d:])\d\d:\d\d:\d\d(?![\d:])", image)
    if not date or not clock:
        return None
    return date.group(0).decode() + " " + clock.group(0).decode()


def validate_image(image: bytes) -> dict:
    """Refuse anything that would not boot, or that cannot be updated again."""
    if not 32 * 1024 <= len(image) <= MAX_IMAGE:
        raise FirmwareImageError(
            f"Dateigröße {len(image)} Byte unplausibel (erlaubt 32 KB bis {MAX_IMAGE // 1024} KB)")
    stack, reset = struct.unpack_from("<II", image, 0)
    if not (SRAM_BASE < stack <= SRAM_END and APP_BASE <= (reset & ~1) < FLASH_END):
        raise FirmwareImageError(
            "Keine SKR-Mini-MZ-Firmware für den BTT-Bootloader (Startadresse 0x08007000)")
    if b"LumaCut CNC" not in image:
        raise FirmwareImageError("LumaCut-Kennung fehlt: fremde Firmware wird nicht geflasht")
    if b"Switching to Binary Protocol" not in image:
        # Without BINARY_FILE_TRANSFER the next update would need the SD card again.
        raise FirmwareImageError(
            "Firmware ohne BINARY_FILE_TRANSFER: danach wäre kein Update über den Pi mehr möglich")
    return {"bytes": len(image), "build": build_stamp(image)}


class BinaryUploader:
    """Marlin binary file transfer over an already open pyserial port."""

    def __init__(self, serial, log=None, packet_timeout: float = 3.0):
        self.serial = serial
        self.log = log or (lambda line: None)
        self.packet_timeout = packet_timeout
        self.sync = 0
        self.max_payload = 0

    def _line(self, deadline: float) -> str:
        while time.monotonic() < deadline:
            raw = self.serial.readline()
            if raw:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self.log(line)
                    return line
        raise TransferError("SKR antwortet nicht während der Firmware-Übertragung")

    def _expect(self, predicate, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while True:
            line = self._line(deadline)
            if line.startswith("fe"):
                raise TransferError("Marlin meldet fatalen Übertragungsfehler: " + line)
            if predicate(line):
                return line

    def _send(self, protocol: int, ptype: int, payload: bytes = b"", retries: int = 5):
        for _ in range(retries):
            self.serial.write(build_packet(self.sync, protocol, ptype, payload))
            deadline = time.monotonic() + self.packet_timeout
            while True:
                try:
                    line = self._line(deadline)
                except TransferError:
                    break  # timeout: resend the same packet
                if line.startswith("fe"):
                    raise TransferError("Marlin meldet fatalen Übertragungsfehler: " + line)
                if line == f"ok{self.sync}":
                    self.sync = (self.sync + 1) & 0xFF
                    return
                if line.startswith("rs"):
                    break
        raise TransferError(f"Paket {self.sync} nach {retries} Versuchen nicht bestätigt")

    def _pft(self, timeout: float = 10.0) -> str:
        return self._expect(lambda line: line.startswith(("PFT:", "PTF:")), timeout)

    def upload(self, filename: str, data: bytes, progress=None):
        self.serial.write(b"M28 B1\n")
        self._expect(lambda line: line.lower().startswith("ok"), 5.0)
        # Short pause so Marlin's queue switches the port into binary mode.
        time.sleep(0.1)
        self.serial.write(build_packet(0, PROTOCOL_CONTROL, CONTROL_SYNC))
        reply = self._expect(lambda line: re.match(r"^ss\d+,\d+,", line) is not None, 5.0)
        sync, size = re.match(r"^ss(\d+),(\d+),", reply).groups()
        self.sync, self.max_payload = int(sync), int(size)
        if self.max_payload < 16:
            raise TransferError("Marlin meldet unbrauchbare Paketgröße " + size)
        try:
            # payload: dummy flag, compression flag, NUL-terminated 8.3 name
            self._send(PROTOCOL_FILE, FILE_OPEN, b"\x00\x00" + filename.encode("ascii") + b"\x00")
            if self._pft() != "PFT:success":
                raise TransferError("SD-Datei konnte nicht geöffnet werden (SD-Karte im SKR?)")
            sent = 0
            while sent < len(data):
                chunk = data[sent:sent + self.max_payload]
                self._send(PROTOCOL_FILE, FILE_WRITE, chunk)
                sent += len(chunk)
                if progress:
                    progress(sent, len(data))
            self._send(PROTOCOL_FILE, FILE_CLOSE)
            if self._pft() != "PFT:success":
                raise TransferError("SD-Datei konnte nicht geschlossen werden")
        except Exception:
            try:
                self._send(PROTOCOL_FILE, FILE_ABORT, retries=1)
            except Exception:
                pass
            raise
        finally:
            try:
                self._send(PROTOCOL_CONTROL, CONTROL_CLOSE, retries=2)
            except Exception:
                pass
