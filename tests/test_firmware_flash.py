"""SKR firmware update over the Pi: binary transfer, M997, verification."""
import struct
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from marlin import firmware_flash as ff
from marlin.transport import MarlinTransport


def fake_image(build="Oct 26 2026 10:11:12", binary=True, lumacut=True, size=64 * 1024):
    head = struct.pack("<II", 0x2000C000, 0x08007000 + 0x1235)
    body = b"FIRMWARE_NAME:Marlin " + build.encode()
    if lumacut:
        body += b"\x00LumaCut CNC Marlin\x00"
    if binary:
        body += b"Switching to Binary Protocol\x00"
    return (head + body).ljust(size, b"\xff")


class MarlinBinaryReceiver:
    """Device side of Marlin binary_stream.h, transcribed for the tests."""

    def __init__(self, max_payload=96, corrupt_packets=()):
        self.max_payload = max_payload
        self.sync = 0
        self.files = {}
        self.current = None
        self.corrupt = set(corrupt_packets)
        self.seen = 0
        self.ascii = True

    def feed(self, raw: bytes):
        replies = []
        while raw:
            if raw[:2] != struct.pack("<H", ff.HEADER_TOKEN):
                raise AssertionError("stream does not start with header token")
            sync, meta, size, header_cs = struct.unpack_from("<BBHH", raw, 2)
            assert header_cs == ff.fletcher16(raw[2:6]), "header checksum"
            payload = raw[8:8 + size]
            consumed = 8 + (size + 2 if size else 0)
            if size:
                footer, = struct.unpack_from("<H", raw, 8 + size)
                assert footer == ff.fletcher16(payload, ff.fletcher16(raw[2:8])), "footer"
            raw = raw[consumed:]
            protocol, ptype = meta >> 4, meta & 0xF
            if protocol == ff.PROTOCOL_CONTROL and ptype == ff.CONTROL_SYNC:
                replies.append(f"ss{self.sync},{self.max_payload},0.1.0")
                continue
            self.seen += 1
            if self.seen in self.corrupt:
                replies.append(f"rs{self.sync}")
                continue
            if sync != self.sync:
                replies.append(f"ok{sync}" if sync == (self.sync - 1) & 0xFF else f"rs{self.sync}")
                continue
            assert size <= self.max_payload
            self.sync = (self.sync + 1) & 0xFF
            replies.append(f"ok{sync}")
            if protocol == ff.PROTOCOL_CONTROL and ptype == ff.CONTROL_CLOSE:
                self.ascii = True
            elif ptype == ff.FILE_OPEN:
                assert payload[:2] == b"\x00\x00" and payload.endswith(b"\x00")
                self.current = payload[2:-1].decode()
                self.files[self.current] = bytearray()
                replies.append("PFT:success")
            elif ptype == ff.FILE_WRITE:
                self.files[self.current] += payload
            elif ptype == ff.FILE_CLOSE:
                replies.append("PFT:success")
        return replies


class SKRSim:
    """USB serial of a LumaCut SKR: ASCII G-code plus binary transfer mode."""

    def __init__(self, build="Oct 25 2026 22:22:08", sd=True, binary=True, receiver=None):
        self.build = build
        self.sd = sd
        self.binary = binary
        self.receiver = receiver or MarlinBinaryReceiver()
        self.out = []
        self.writes = []
        self.binary_mode = False
        self.rebooted = False
        self.closed = False

    def identity(self):
        return (f"FIRMWARE_NAME:Marlin 2.1.2.9 ({self.build}) SOURCE_CODE_URL:github.com/"
                "MarlinFirmware/Marlin PROTOCOL_VERSION:1.0 MACHINE_TYPE:LumaCut CNC Marlin")

    def write(self, raw):
        self.writes.append(raw)
        if self.binary_mode:
            for reply in self.receiver.feed(raw):
                self.out.append(reply + "\n")
            if self.receiver.ascii:
                self.binary_mode = False
            return len(raw)
        cmd = raw.decode().strip()
        if cmd == "M115":
            self.out += [self.identity() + "\n", "Cap:Z_PROBE:1\n",
                         f"Cap:BINARY_FILE_TRANSFER:{int(self.binary)}\n"]
        elif cmd == "M21":
            self.out.append("echo:SD card ok\n" if self.sd else "echo:No SD card\n")
        elif cmd == "M28 B1":
            self.out.append("echo:Switching to Binary Protocol\n")
            self.binary_mode = True
            self.receiver.ascii = False
        elif cmd == "M997":
            data = bytes(self.receiver.files.get(ff.TARGET_NAME, b""))
            self.rebooted = True
            stamp = ff.build_stamp(data)
            if stamp:
                self.build = stamp
            return len(raw)
        self.out.append("ok P15 B7\n")
        return len(raw)

    def readline(self):
        return self.out.pop(0).encode() if self.out else b""

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FirmwareBuildTests(unittest.TestCase):
    def test_build_enables_binary_transfer_for_pi_updates(self):
        source = (Path(__file__).resolve().parents[1] / "firmware" / "marlin" / "build.py").read_text(encoding="utf-8")
        self.assertIn('adv = uncomment(adv, "BINARY_FILE_TRANSFER")', source)


class ImageValidationTests(unittest.TestCase):
    def test_accepts_lumacut_image_and_reads_build_stamp(self):
        info = ff.validate_image(fake_image())
        self.assertEqual(info["build"], "Oct 26 2026 10:11:12")

    def test_real_build_stamp_from_marlin_binary_format(self):
        # __DATE__ pads single-digit days with a space ("Nov  5 2026").
        self.assertEqual(ff.build_stamp(b"x\x00Nov  5 2026\x0007:08:09\x00"), "Nov  5 2026 07:08:09")

    def test_rejects_images_that_would_brick_or_lock_out_updates(self):
        cases = {
            "Dateigröße": fake_image(size=1024),
            "Startadresse": b"\x00" * 8 + fake_image()[8:],
            "LumaCut-Kennung": fake_image(lumacut=False),
            "BINARY_FILE_TRANSFER": fake_image(binary=False),
        }
        for reason, image in cases.items():
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ff.FirmwareImageError, reason):
                    ff.validate_image(image)


class BinaryProtocolTests(unittest.TestCase):
    def test_packet_layout_matches_marlin_header(self):
        packet = ff.build_packet(7, ff.PROTOCOL_FILE, ff.FILE_WRITE, b"abc")
        self.assertEqual(packet[:2], b"\xad\xb5")      # 0xB5AD little endian
        self.assertEqual(packet[2], 7)
        self.assertEqual(packet[3], 0x13)               # protocol 1, type 3
        self.assertEqual(struct.unpack_from("<H", packet, 4)[0], 3)
        self.assertEqual(len(packet), 8 + 3 + 2)
        self.assertEqual(len(ff.build_packet(0, 0, ff.CONTROL_SYNC)), 8)  # no footer

    def test_upload_transfers_exact_bytes_with_resend(self):
        receiver = MarlinBinaryReceiver(max_payload=96, corrupt_packets={5, 9})
        sim = SKRSim(receiver=receiver)
        image = bytes(range(256)) * 41  # 10496 bytes, not a multiple of 96
        progress = []
        ff.BinaryUploader(sim, packet_timeout=0.2).upload(
            "firmware.bin", image, lambda done, total: progress.append(done))
        self.assertEqual(bytes(receiver.files["firmware.bin"]), image)
        self.assertEqual(progress[-1], len(image))
        self.assertTrue(receiver.ascii, "binary mode closed again")
        self.assertFalse(sim.binary_mode)

    def test_sync_wraps_after_255_packets(self):
        receiver = MarlinBinaryReceiver(max_payload=16)
        sim = SKRSim(receiver=receiver)
        image = b"\x5a" * (16 * 300)
        ff.BinaryUploader(sim, packet_timeout=0.2).upload("firmware.bin", image)
        self.assertEqual(bytes(receiver.files["firmware.bin"]), image)


class FlashWorkflowTests(unittest.TestCase):
    def _connected(self, sim):
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
        bridge.ensure_ready()
        sim.writes.clear()
        return bridge

    def test_flash_uploads_reboots_and_verifies_new_build(self):
        sim = SKRSim()
        bridge = self._connected(sim)
        self.assertTrue(bridge.status()["firmware_upload_supported"])
        bridge.homed = True
        image = fake_image(build="Oct 26 2026 10:11:12")
        message = bridge.flash_firmware(image, settle_timeout=5, boot_wait=0, poll=0.05)
        self.assertIn("Oct 26 2026 10:11:12", message)
        self.assertEqual(bytes(sim.receiver.files["firmware.bin"]), image)
        commands = [w for w in sim.writes if w.endswith(b"\n") and w[:1] in b"GM"]
        order = [commands.index(c) for c in (b"M5 I\n", b"M107 P0\n", b"M21\n",
                                             b"M30 firmware.bin\n", b"M28 B1\n", b"M997\n")]
        self.assertEqual(order, sorted(order))
        status = bridge.status()
        self.assertEqual(status["firmware_update"]["state"], "done")
        self.assertFalse(status["homed"], "fresh firmware must be homed again")
        self.assertEqual(status["owner"], "Frei")

    def test_flash_reports_when_bootloader_kept_old_firmware(self):
        sim = SKRSim()
        bridge = self._connected(sim)
        sim.write = (lambda original: (lambda raw: 0 if raw == b"M997\n" else original(raw)))(sim.write)
        with self.assertRaisesRegex(RuntimeError, "nicht mit dem neuen Build"):
            bridge.flash_firmware(fake_image(), settle_timeout=5, boot_wait=0, poll=0.05)
        self.assertEqual(bridge.status()["firmware_update"]["state"], "error")
        self.assertEqual(bridge.status()["owner"], "Frei")

    def test_flash_refuses_without_sd_card_before_writing(self):
        sim = SKRSim(sd=False)
        bridge = self._connected(sim)
        with self.assertRaisesRegex(RuntimeError, "Keine SD-Karte"):
            bridge.flash_firmware(fake_image(), settle_timeout=1, boot_wait=0, poll=0.05)
        self.assertNotIn(b"M28 B1\n", sim.writes)
        self.assertNotIn(b"M997\n", sim.writes)

    def test_flash_refuses_old_firmware_without_binary_transfer(self):
        bridge = self._connected(SKRSim(binary=False))
        with self.assertRaisesRegex(RuntimeError, "SD-Karte flashen"):
            bridge.flash_firmware(fake_image())

    def test_flash_refuses_while_lightburn_owns_the_machine(self):
        bridge = self._connected(SKRSim())
        bridge.owner = "lightburn"
        with self.assertRaisesRegex(RuntimeError, "belegt"):
            bridge.flash_firmware(fake_image())

    def test_status_stays_readable_during_upload(self):
        sim = SKRSim(receiver=MarlinBinaryReceiver(max_payload=16))
        bridge = self._connected(sim)
        seen = []
        worker = threading.Thread(target=lambda: bridge.flash_firmware(
            fake_image(size=48 * 1024), settle_timeout=5, boot_wait=0, poll=0.05))
        worker.start()
        deadline = time.monotonic() + 10
        while worker.is_alive() and time.monotonic() < deadline:
            started = time.monotonic()
            seen.append(bridge.status()["firmware_update"]["state"])
            self.assertLess(time.monotonic() - started, 1.0)
            time.sleep(0.01)
        worker.join(5)
        self.assertIn("uploading", seen)


class EmergencyResetTests(unittest.TestCase):
    def test_latch_clears_only_when_skr_answers_after_reset(self):
        sim = SKRSim()
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
        bridge.ensure_ready()
        bridge.emergency_latched = True
        bridge.homed = True
        self.assertIn("quittiert", bridge.clear_emergency())
        self.assertFalse(bridge.emergency_latched)
        self.assertFalse(bridge.homed)

    def test_latch_stays_when_killed_marlin_is_silent(self):
        silent = SKRSim()
        silent.write = lambda raw: len(raw)  # Marlin in kill(): no replies
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: silent)
        bridge.emergency_latched = True
        with self.assertRaisesRegex(RuntimeError, "Reset-Taste"):
            bridge.clear_emergency()
        self.assertTrue(bridge.emergency_latched)


if __name__ == "__main__":
    unittest.main()
