import unittest

from pi400.marlin import avr_flash
from pi400.marlin.avr_flash import FlashError, Stk500, flash, parse_hex, validate_hex
from pi400.marlin.firmware_flash import FirmwareImageError


def to_hex(image: bytes) -> str:
    """Intel HEX the way avr-objcopy writes it (16 bytes per record)."""
    lines, base = [], -1
    for start in range(0, len(image), 16):
        if start >> 16 != base:
            base = start >> 16
            rec = bytes((2, 0, 0, 4)) + base.to_bytes(2, "big")
            lines.append(":" + (rec + bytes(((-sum(rec)) & 0xFF,))).hex().upper())
        chunk = image[start:start + 16]
        rec = bytes((len(chunk), (start >> 8) & 0xFF, start & 0xFF, 0)) + chunk
        lines.append(":" + (rec + bytes(((-sum(rec)) & 0xFF,))).hex().upper())
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def lumacut_image(size=20000) -> bytes:
    body = bytearray(b"\x0c\x94" + bytes(range(256)) * (size // 256))
    stamp = b"LumaCut CNC Marlin Anet\x00Oct 31 2026\x0016:54:31\x00"
    body[300:300 + len(stamp)] = stamp
    return bytes(body[:size])


class FakeBootloader:
    """STK500 v1 as Optiboot answers it, with 128 KB of flash."""

    def __init__(self, signature=avr_flash.SIGNATURE, alive=True, corrupt_at=None):
        self.flash = bytearray(b"\xff" * 131072)
        self.signature = signature
        self.alive = alive
        self.corrupt_at = corrupt_at
        self.rx = b""
        self.address = 0
        self.dtr = self.rts = False
        self.closed = False
        self.started_app = False
        self.timeout = 0.05

    def reset_input_buffer(self):
        self.rx = b""

    def write(self, data):
        if not self.alive:
            return len(data)
        cmd = data[0]
        ok = b"\x14\x10"
        if cmd == 0x30 or cmd == 0x50:
            self.rx += ok
        elif cmd == 0x75:
            self.rx += b"\x14" + self.signature + b"\x10"
        elif cmd == 0x55:
            self.address = (data[1] | (data[2] << 8)) * 2
            self.rx += ok
        elif cmd == 0x64:
            n = (data[1] << 8) | data[2]
            self.flash[self.address:self.address + n] = data[4:4 + n]
            if self.corrupt_at is not None and self.address <= self.corrupt_at < self.address + n:
                self.flash[self.corrupt_at] ^= 0xFF
            self.rx += ok
        elif cmd == 0x74:
            n = (data[1] << 8) | data[2]
            self.rx += b"\x14" + bytes(self.flash[self.address:self.address + n]) + b"\x10"
        elif cmd == 0x51:
            self.started_app = True
            self.rx += ok
        return len(data)

    def read(self, n):
        out, self.rx = self.rx[:n], self.rx[n:]
        return out

    def close(self):
        self.closed = True


class HexTest(unittest.TestCase):
    def test_round_trip_and_identity(self):
        image = lumacut_image()
        info = validate_hex(to_hex(image))
        self.assertEqual(info["image"], image)
        self.assertEqual(info["build"], "Oct 31 2026 16:54:31")

    def test_foreign_or_broken_images_are_refused(self):
        foreign = bytearray(lumacut_image())
        foreign[300:323] = b"x" * 23
        for text, why in ((to_hex(bytes(foreign)), "LumaCut"),
                          (to_hex(b"\x00\x00" + lumacut_image()[2:]), "AVR"),
                          (to_hex(lumacut_image(4096)), "klein"),
                          (to_hex(lumacut_image()).replace(":10", ":11", 1), "Prüfsumme")):
            with self.assertRaisesRegex(FirmwareImageError, why):
                validate_hex(text)

    def test_image_into_the_boot_loader_is_refused(self):
        with self.assertRaisesRegex(FirmwareImageError, "Bootloader"):
            parse_hex(to_hex(lumacut_image(avr_flash.MAX_APP + 256)))


class FlashTest(unittest.TestCase):
    def test_writes_verifies_and_starts_marlin(self):
        image = lumacut_image()
        boot, seen = FakeBootloader(), []
        flash(boot, image, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(bytes(boot.flash[:len(image)]), image)
        self.assertTrue(boot.started_app)
        pages = (len(image) + 255) // 256
        self.assertEqual(seen[-1], (2 * pages, 2 * pages))

    def test_wrong_chip_is_never_written(self):
        boot = FakeBootloader(signature=b"\x1e\x95\x0f")     # ATmega328P
        with self.assertRaisesRegex(FlashError, "Falscher Chip"):
            flash(boot, lumacut_image())
        self.assertEqual(set(boot.flash), {0xFF})

    def test_no_boot_loader_no_write(self):
        boot = FakeBootloader(alive=False)                    # e.g. the Atomstack ESP32
        with self.assertRaisesRegex(FlashError, "Kein Bootloader"):
            Stk500(boot).reset_and_sync(tries=1)

    def test_verify_catches_a_bad_page(self):
        with self.assertRaisesRegex(FlashError, "0x00105"):
            flash(FakeBootloader(corrupt_at=0x105), lumacut_image())


class TransportFlashTest(unittest.TestCase):
    def test_flash_avr_reconnects_and_checks_the_build(self):
        from pi400.marlin.transport import MarlinTransport
        boot = FakeBootloader()
        m = MarlinTransport("/dev/null")
        connects = []

        def ensure_ready(owner=None):
            connects.append(owner)
            m.identity = "FIRMWARE_NAME:Marlin 2.1.2.9 (Oct 31 2026 16:54:31) MACHINE_TYPE:LumaCut CNC Marlin Anet"
            m.serial = object()
        m.ensure_ready = ensure_ready
        message = m.flash_avr(to_hex(lumacut_image()), port="/dev/ttyUSB0",
                              opener=lambda port, baud: boot, poll=0.01)
        self.assertIn("Oct 31 2026 16:54:31", message)
        self.assertEqual(connects, ["firmware"])
        self.assertTrue(boot.closed)
        self.assertIsNone(m.owner)
        self.assertEqual(m.firmware["state"], "done")

    def test_flash_avr_refuses_while_busy(self):
        from pi400.marlin.transport import MarlinTransport
        m = MarlinTransport("/dev/null")
        m.owner = "job"
        with self.assertRaisesRegex(RuntimeError, "belegt"):
            m.flash_avr(to_hex(lumacut_image()), port="/dev/ttyUSB0",
                        opener=lambda port, baud: FakeBootloader())


if __name__ == "__main__":
    unittest.main()
