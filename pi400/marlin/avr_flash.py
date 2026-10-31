"""Flash the Anet V1.0/V1.7 board (ATmega1284P) over USB from the Pi.

The board carries an Optiboot-style boot loader that speaks STK500 v1
(avrdude "-c arduino", 115200 baud): opening the port pulses DTR, the
CH340's DTR line resets the chip through a capacitor, and the boot loader
listens for about a second before it starts Marlin. Implemented here in
plain pyserial so the Pi needs no avrdude:

  GET_SYNC      30 20            -> 14 10
  READ_SIGN     75 20            -> 14 s1 s2 s3 10
  ENTER_PROG    50 20            -> 14 10
  LOAD_ADDRESS  55 lo hi 20      -> 14 10       (word address)
  PROG_PAGE     64 nh nl 46 d.. 20 -> 14 10     ('F' = flash)
  READ_PAGE     74 nh nl 46 20   -> 14 d.. 10
  LEAVE_PROG    51 20            -> 14 10       (boot loader starts the app)

Nothing is written unless the chip reports the ATmega1284P signature and
the image is a LumaCut Anet build (firmware/marlin/build_anet.py); every
page is read back and compared afterwards.
"""
from __future__ import annotations

import time

from .firmware_flash import FirmwareImageError, build_stamp

SIGNATURE = bytes((0x1E, 0x97, 0x05))      # ATmega1284P
PAGE = 256                                 # flash page size in bytes
# Application space below the boot loader (the largest 1284P boot section
# is 4 KB; Marlin's sanguino1284p env uses the same limit).
MAX_APP = 126976
BOOT_BAUD = 115200
IDENTITY = b"LumaCut CNC Marlin Anet"

STK_OK, STK_INSYNC, CRC_EOP = 0x10, 0x14, 0x20


class FlashError(RuntimeError):
    """The boot loader did not answer as expected; see the message."""


def parse_hex(text: str) -> bytes:
    """Intel HEX -> flash image from address 0 (gaps filled with 0xFF)."""
    image = bytearray(b"\xff" * MAX_APP)
    top, base = 0, 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise FirmwareImageError("Zeile %d ist kein Intel-HEX" % number)
        try:
            data = bytes.fromhex(line[1:])
        except ValueError:
            raise FirmwareImageError("Zeile %d: ungültige Hex-Zeichen" % number) from None
        if len(data) < 5 or len(data) != data[0] + 5 or sum(data) & 0xFF:
            raise FirmwareImageError("Zeile %d: Länge oder Prüfsumme falsch" % number)
        count, address, kind = data[0], (data[1] << 8) | data[2], data[3]
        payload = data[4:4 + count]
        if kind == 0:
            start = base + address
            if start + count > MAX_APP:
                raise FirmwareImageError("Image reicht in den Bootloader (über %d Byte)" % MAX_APP)
            image[start:start + count] = payload
            top = max(top, start + count)
        elif kind == 1:
            break
        elif kind == 2:
            base = int.from_bytes(payload, "big") << 4
        elif kind == 4:
            base = int.from_bytes(payload, "big") << 16
        elif kind in (3, 5):
            continue        # start address records: not used on AVR
        else:
            raise FirmwareImageError("Zeile %d: unbekannter Satztyp %d" % (number, kind))
    return bytes(image[:top])


def validate_hex(text: str) -> dict:
    """A LumaCut Anet image: AVR vector table, identity string, sane size."""
    image = parse_hex(text)
    if len(image) < 16 * 1024:
        raise FirmwareImageError("Image zu klein (%d Byte)" % len(image))
    if image[0:2] != b"\x0c\x94":
        raise FirmwareImageError("Kein AVR-Programm (Sprungtabelle fehlt)")
    if IDENTITY not in image:
        raise FirmwareImageError("Keine LumaCut-Anet-Firmware (build_anet.py)")
    return {"bytes": len(image), "build": build_stamp(image), "image": image}


class Stk500:
    def __init__(self, ser, log=None):
        self.ser = ser
        self.log = log or (lambda line: None)

    def _read(self, n: int, timeout: float = 1.0) -> bytes:
        data, end = b"", time.monotonic() + timeout
        while len(data) < n and time.monotonic() < end:
            data += self.ser.read(n - len(data))
        return data

    def _command(self, body: bytes, reply_len: int = 0, timeout: float = 1.0) -> bytes:
        self.ser.write(body + bytes((CRC_EOP,)))
        reply = self._read(reply_len + 2, timeout)
        if len(reply) != reply_len + 2 or reply[0] != STK_INSYNC or reply[-1] != STK_OK:
            raise FlashError("Bootloader antwortet nicht passend auf %02X (%s)" % (body[0], reply.hex()))
        return reply[1:-1]

    def reset_and_sync(self, tries: int = 3):
        """Pulse DTR/RTS (auto-reset), then catch the boot loader's window.

        Measured on the owner's board: the boot loader blinks first and only
        listens ~0.45 s after the reset edge, then starts Marlin about 1 s
        later unless commands keep coming. Exactly one GET_SYNC is in flight
        at a time and its answer is awaited, never flushed: the chip's
        2-byte receive FIFO keeps an early pair aligned, while extra bytes
        make Optiboot treat a stray 0x20 as a command and start Marlin.
        """
        for attempt in range(tries):
            self.ser.dtr = self.ser.rts = False
            time.sleep(0.25)
            self.ser.reset_input_buffer()
            self.ser.dtr = self.ser.rts = True        # falling edge resets the chip
            time.sleep(0.3)
            for _ in range(3):
                self.ser.write(bytes((0x30, CRC_EOP)))
                reply = self._read(2, 0.5)
                if reply == bytes((STK_INSYNC, STK_OK)):
                    try:
                        self._command(b"\x30")        # one clean round trip proves alignment
                        return
                    except FlashError:
                        break
                if reply:
                    break                             # Marlin's banner: missed the window
            self.log("STK500: kein Sync (Versuch %d)" % (attempt + 1))
        raise FlashError("Kein Bootloader am Port (Sync fehlgeschlagen)")

    def signature(self) -> bytes:
        return self._command(b"\x75", 3)

    def _address(self, byte_address: int):
        word = byte_address >> 1
        self._command(bytes((0x55, word & 0xFF, (word >> 8) & 0xFF)))

    def write(self, image: bytes, progress=None):
        self._command(b"\x50")
        pages = (len(image) + PAGE - 1) // PAGE
        for i in range(pages):
            chunk = image[i * PAGE:(i + 1) * PAGE].ljust(PAGE, b"\xff")
            self._address(i * PAGE)
            self._command(bytes((0x64, PAGE >> 8, PAGE & 0xFF, 0x46)) + chunk, timeout=2.0)
            if progress:
                progress(i + 1, 2 * pages)

    def read(self, length: int, progress=None, done_before: int = 0, total: int = 0) -> bytes:
        pages = (length + PAGE - 1) // PAGE
        out = bytearray()
        for i in range(pages):
            self._address(i * PAGE)
            out += self._command(bytes((0x74, PAGE >> 8, PAGE & 0xFF, 0x46)), PAGE, timeout=2.0)
            if progress:
                progress(done_before + i + 1, total or pages)
        return bytes(out[:length])

    def leave(self):
        try:
            self._command(b"\x51")
        except FlashError:
            pass        # some boot loaders jump to the app before answering


def flash(ser, image: bytes, progress=None, log=None) -> None:
    """Reset into the boot loader, check the chip, write, verify, start Marlin."""
    stk = Stk500(ser, log)
    stk.reset_and_sync()
    sig = stk.signature()
    if sig != SIGNATURE:
        raise FlashError("Falscher Chip: Signatur %s statt %s (ATmega1284P)" % (sig.hex(" "), SIGNATURE.hex(" ")))
    stk.write(image, progress)
    pages = (len(image) + PAGE - 1) // PAGE
    back = stk.read(len(image), progress, done_before=pages, total=2 * pages)
    if back != image:
        bad = next(i for i, (a, b) in enumerate(zip(back, image)) if a != b)
        raise FlashError("Prüfen nach dem Schreiben fehlgeschlagen bei Byte 0x%05X" % bad)
    stk.leave()
