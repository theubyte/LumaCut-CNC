"""SKR firmware update over the Pi: M997 self-update and its verification."""
import struct
import sys
import threading
import time
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from marlin import firmware_flash as ff
from marlin.transport import MarlinTransport

OLD_BUILD = "Oct 25 2026 22:22:08"
NEW_BUILD = "Oct 26 2026 10:11:12"


def fake_image(build=NEW_BUILD, self_update=True, lumacut=True, size=64 * 1024):
    head = struct.pack("<II", 0x20010000, 0x08007000 + 0x1235)
    body = b""
    if lumacut:
        body += b"FIRMWARE_NAME:LumaCut CNC 0.1 (" + build.encode() + b") MACHINE_TYPE:LumaCut CNC\x00"
    if self_update:
        body += b"Cap:SELF_UPDATE:1\x00"
    return (head + body).ljust(size, b"\xff")


def marlin_image():
    """What the old CI built: LumaCut name, Marlin's binary transfer, no M997 update."""
    head = struct.pack("<II", 0x2000C000, 0x08007000 + 0x1235)
    return (head + b"FIRMWARE_NAME:Marlin 2.1.2.9 Oct 26 2026 10:11:12 MACHINE_TYPE:LumaCut CNC Marlin\x00"
            b"Switching to Binary Protocol\x00").ljust(128 * 1024, b"\xff")


class SKRSim:
    """USB serial of the firmware: G-code plus the raw bytes after M997, per contract."""

    def __init__(self, build=OLD_BUILD, self_update=True, chunk=1024, reject=None,
                 bad_offset_at=None, silent_after=None, keep_old=False, done_in_last_ack=False):
        self.build = build
        self.self_update = self_update
        self.chunk = chunk
        self.reject = reject                 # text of an Error: answer to M997
        self.bad_offset_at = bad_offset_at   # block number with a wrong ok <offset>
        self.silent_after = silent_after     # block number after which nothing comes back
        self.keep_old = keep_old             # the copy did not take: old build after restart
        self.done_in_last_ack = done_in_last_ack
        self.out = []
        self.writes = []
        self.expect = 0
        self.crc = 0
        self.data = bytearray()
        self.blocks = 0
        self.flashed = None
        self.closed = False

    def identity(self):
        return f"FIRMWARE_NAME:LumaCut CNC 0.1 ({self.build}) MACHINE_TYPE:LumaCut CNC"

    def write(self, raw):
        self.writes.append(raw)
        if self.expect:
            return self._receive(raw)
        cmd = raw.decode().strip()
        if cmd == "M115":
            self.out += [self.identity() + "\n", "Cap:Z_PROBE:1\n",
                         f"Cap:SELF_UPDATE:{int(self.self_update)}\n"]
        elif cmd.startswith("M997"):
            if self.reject:
                self.out += [f"Error:{self.reject}\n", "ok P32 B16\n"]
                return len(raw)
            size, self.crc = int(cmd.split()[1][1:]), int(cmd.split()[2][1:])
            self.expect, self.data = size, bytearray()
            self.out.append(f"ok READY {self.chunk}\n")
            return len(raw)
        self.out.append("ok P32 B16\n")
        return len(raw)

    def _receive(self, raw):
        assert len(raw) <= self.chunk, "block larger than the chunk the firmware asked for"
        self.data += raw
        self.blocks += 1
        if self.silent_after is not None and self.blocks > self.silent_after:
            return len(raw)
        finished = len(self.data) >= self.expect
        offset = len(self.data)
        if self.blocks == self.bad_offset_at:
            offset -= 1
        if not (finished and self.done_in_last_ack):
            self.out.append(f"ok {offset}\n")
        if finished:
            self.expect = 0
            if zlib.crc32(bytes(self.data)) & 0xFFFFFFFF != self.crc:
                self.out += ["Error:Update CRC\n", "ok P32 B16\n"]
                return len(raw)
            self.out.append("ok DONE\n")
            self.flashed = bytes(self.data)
            if not self.keep_old:
                self.build = ff.build_stamp(self.flashed)
        return len(raw)

    def readline(self):
        if not self.out:
            time.sleep(0.001)
            return b""
        return self.out.pop(0).encode()

    def reset_input_buffer(self):
        self.out.clear()

    def flush(self):
        pass

    def close(self):
        self.closed = True


class ImageValidationTests(unittest.TestCase):
    def test_accepts_lumacut_image_and_reads_build_stamp(self):
        info = ff.validate_image(fake_image())
        self.assertEqual(info["build"], NEW_BUILD)
        self.assertEqual(info["bytes"], 64 * 1024)

    def test_a_small_firmware_is_fine(self):
        self.assertEqual(ff.validate_image(fake_image(size=20 * 1024))["bytes"], 20 * 1024)

    def test_real_build_stamp_from_binary_format(self):
        # __DATE__ pads single-digit days with a space ("Nov  5 2026").
        self.assertEqual(ff.build_stamp(b"x\x00Nov  5 2026\x0007:08:09\x00"), "Nov  5 2026 07:08:09")

    def test_rejects_images_that_would_brick_or_lock_out_updates(self):
        cases = {
            "Dateigröße": fake_image(size=1024),
            "Startadresse": b"\x00" * 8 + fake_image()[8:],
            "LumaCut-Kennung": fake_image(lumacut=False),
            "SELF_UPDATE": fake_image(self_update=False),
        }
        for reason, image in cases.items():
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ff.FirmwareImageError, reason):
                    ff.validate_image(image)

    def test_size_limit_is_the_contract_s_196_kb(self):
        self.assertEqual(ff.validate_image(fake_image(size=196 * 1024))["bytes"], 196 * 1024)
        with self.assertRaisesRegex(ff.FirmwareImageError, "Dateigröße"):
            ff.validate_image(fake_image(size=196 * 1024 + 1))

    def test_start_address_other_than_the_bootloader_s_is_refused(self):
        wrong = struct.pack("<II", 0x20010000, 0x08000000 + 0x1235) + fake_image()[8:]
        with self.assertRaisesRegex(ff.FirmwareImageError, "Startadresse"):
            ff.validate_image(wrong)

    def test_old_marlin_image_is_refused(self):
        with self.assertRaisesRegex(ff.FirmwareImageError, "SELF_UPDATE"):
            ff.validate_image(marlin_image())


class UploaderTests(unittest.TestCase):
    def test_command_carries_size_and_zlib_crc(self):
        image = b"123456789" * 1000
        self.assertEqual(ff.update_command(image), "M997 U9000 C%d" % zlib.crc32(image))
        self.assertEqual(zlib.crc32(b"123456789"), 0xCBF43926)   # IEEE 802.3 check value

    def test_upload_transfers_exact_bytes_in_chunks(self):
        sim = SKRSim(chunk=1024)
        image = bytes(range(256)) * 41  # 10496 bytes, not a multiple of 1024
        progress = []
        ff.SelfUpdateUploader(sim).upload(image, lambda done, total: progress.append(done))
        self.assertEqual(sim.flashed, image)
        self.assertEqual(progress[-1], len(image))
        self.assertEqual(sim.blocks, 11)
        self.assertEqual(sim.writes[0], ff.update_command(image).encode() + b"\n")

    def test_done_right_after_the_last_block_counts_too(self):
        sim = SKRSim(done_in_last_ack=True)
        ff.SelfUpdateUploader(sim).upload(b"\x5a" * 3000)
        self.assertEqual(sim.flashed, b"\x5a" * 3000)

    def test_refusal_wrong_offset_silence_and_bad_chunk_stop_the_transfer(self):
        image = b"\x5a" * 5000
        cases = {
            "lehnt das Update ab": SKRSim(reject="Update refused"),
            "bestätigt Byte": SKRSim(bad_offset_at=2),
            "antwortet nicht": SKRSim(silent_after=1),
            "Blockgröße": SKRSim(chunk=4),
        }
        for reason, sim in cases.items():
            with self.subTest(reason=reason):
                up = ff.SelfUpdateUploader(sim, block_timeout=0.1, done_timeout=0.1)
                with self.assertRaisesRegex(ff.TransferError, reason):
                    up.upload(image)
                self.assertIsNone(sim.flashed)


class FlashWorkflowTests(unittest.TestCase):
    def _connected(self, sim):
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
        bridge.ensure_ready()
        sim.writes.clear()
        return bridge

    def test_flash_uploads_and_verifies_new_build(self):
        sim = SKRSim()
        bridge = self._connected(sim)
        self.assertTrue(bridge.status()["firmware_upload_supported"])
        bridge.homed = True
        image = fake_image()
        message = bridge.flash_firmware(image, settle_timeout=5, boot_wait=0, poll=0.05)
        self.assertIn(NEW_BUILD, message)
        self.assertEqual(sim.flashed, image)
        commands = [w for w in sim.writes if w.endswith(b"\n") and w[:1] in b"GM" and len(w) < 96]
        update = ff.update_command(image).encode() + b"\n"
        order = [commands.index(c) for c in (b"M5 I\n", b"M400\n", b"M107 P0\n", b"M9\n", b"M355 S0\n", update)]
        self.assertEqual(order, sorted(order))
        status = bridge.status()
        self.assertEqual(status["firmware_update"]["state"], "done")
        self.assertFalse(status["homed"], "fresh firmware must be homed again")
        self.assertEqual(status["owner"], "Frei")
        self.assertIn(NEW_BUILD, status["identity"])

    def test_old_marlin_upload_is_refused_before_anything_is_sent(self):
        sim = SKRSim()
        bridge = self._connected(sim)
        with self.assertRaises(ff.FirmwareImageError):
            bridge.flash_firmware(marlin_image())
        self.assertEqual(sim.writes, [])

    def test_flash_reports_when_the_old_build_keeps_running(self):
        sim = SKRSim(keep_old=True)
        bridge = self._connected(sim)
        with self.assertRaisesRegex(RuntimeError, "nicht mit dem neuen Build"):
            bridge.flash_firmware(fake_image(), settle_timeout=5, boot_wait=0, poll=0.05)
        self.assertEqual(bridge.status()["firmware_update"]["state"], "error")
        self.assertEqual(bridge.status()["owner"], "Frei")

    def test_abort_keeps_running_firmware_and_never_claims_success(self):
        cases = {
            "lehnt": {"reject": "Update refused"},
            "bestätigt Byte": {"bad_offset_at": 2},
        }
        for reason, kw in cases.items():
            with self.subTest(reason=reason):
                sim = SKRSim(**kw)
                bridge = self._connected(sim)
                bridge.homed = True
                with self.assertRaisesRegex(RuntimeError, "laufende Firmware bleibt.*" + reason):
                    bridge.flash_firmware(fake_image(), settle_timeout=1, boot_wait=0, poll=0.05)
                self.assertIsNone(sim.flashed)
                self.assertEqual(sim.build, OLD_BUILD)
                status = bridge.status()
                self.assertEqual(status["firmware_update"]["state"], "error")
                self.assertEqual(status["owner"], "Frei")
                self.assertTrue(sim.closed, "port closed: the firmware drops the transfer")
                self.assertFalse(status["homed"])
                # The heartbeat connects again and finds the old firmware.
                sim.expect = 0
                bridge.ensure_ready()
                self.assertIn(OLD_BUILD, bridge.status()["identity"])

    def test_bad_checksum_on_the_firmware_side_keeps_it_too(self):
        sim = SKRSim()
        bridge = self._connected(sim)
        original = ff.update_command
        ff.update_command = lambda image: "M997 U%d C1" % len(image)
        self.addCleanup(setattr, ff, "update_command", original)
        with self.assertRaisesRegex(RuntimeError, "laufende Firmware bleibt.*Update CRC"):
            bridge.flash_firmware(fake_image(), settle_timeout=1, boot_wait=0, poll=0.05)
        self.assertIsNone(sim.flashed)

    def test_no_restart_after_update_is_an_error(self):
        sim = SKRSim()
        bridge = self._connected(sim)
        bridge._open = lambda: (_ for _ in ()).throw(OSError("kein USB"))
        with self.assertRaisesRegex(RuntimeError, "nicht wieder erreichbar.*SD-Karte"):
            bridge.flash_firmware(fake_image(), settle_timeout=0.2, boot_wait=0, poll=0.02)
        self.assertEqual(bridge.status()["firmware_update"]["state"], "error")
        self.assertEqual(bridge.status()["owner"], "Frei")

    def test_flash_refuses_firmware_without_self_update(self):
        bridge = self._connected(SKRSim(self_update=False))
        self.assertFalse(bridge.status()["firmware_upload_supported"])
        with self.assertRaisesRegex(RuntimeError, "SD-Karte flashen"):
            bridge.flash_firmware(fake_image())

    def test_flash_refuses_while_lightburn_owns_the_machine(self):
        bridge = self._connected(SKRSim())
        bridge.owner = "lightburn"
        with self.assertRaisesRegex(RuntimeError, "belegt"):
            bridge.flash_firmware(fake_image())

    def test_status_stays_readable_during_upload(self):
        sim = SKRSim(chunk=16)
        bridge = self._connected(sim)
        seen = []
        worker = threading.Thread(target=lambda: bridge.flash_firmware(
            fake_image(size=48 * 1024), settle_timeout=5, boot_wait=0, poll=0.05))
        worker.start()
        deadline = time.monotonic() + 20
        while worker.is_alive() and time.monotonic() < deadline:
            # Only the upload must not block; the reconnect afterwards holds
            # the lock ~1 s by design (STM32 USB settle in ensure_ready).
            if bridge.firmware["state"] == "uploading":
                started = time.monotonic()
                seen.append(bridge.status()["firmware_update"]["state"])
                self.assertLess(time.monotonic() - started, 0.5)
            time.sleep(0.01)
        worker.join(20)
        self.assertIn("uploading", seen)


class EmergencyResetTests(unittest.TestCase):
    def test_latch_clears_with_m999_on_a_fresh_connection(self):
        sim = SKRSim()
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
        bridge.ensure_ready()
        bridge.emergency_latched = True
        bridge.homed = True
        sim.writes.clear()
        self.assertIn("quittiert", bridge.clear_emergency())
        self.assertFalse(bridge.emergency_latched)
        self.assertFalse(bridge.homed)
        self.assertEqual(sim.writes[:3], [b"M115\n", b"M999\n", b"M5 I\n"])

    def test_latch_stays_when_the_board_is_silent(self):
        silent = SKRSim()
        silent.write = lambda raw: len(raw)
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: silent)
        bridge.emergency_latched = True
        with self.assertRaisesRegex(RuntimeError, "Reset-Taste"):
            bridge.clear_emergency()
        self.assertTrue(bridge.emergency_latched)

    def test_still_latched_firmware_latches_the_pi_after_a_service_restart(self):
        # The Pi forgot its latch (service restart), the firmware did not:
        # it must neither be cleared by itself nor stay out of reach.
        class Latched(SKRSim):
            latched = True

            def write(self, raw):
                cmd = raw.decode().strip()
                if self.latched and cmd not in ("M115", "M119", "M999"):
                    self.writes.append(raw)
                    self.out += ["Error:Emergency stop\n", "ok P32 B16\n"]
                    return len(raw)
                if cmd == "M999":
                    self.latched = False
                return super().write(raw)
        sim = Latched()
        bridge = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
        with self.assertRaisesRegex(RuntimeError, "Emergency stop"):
            bridge.ensure_ready()
        self.assertTrue(sim.latched, "no M999 without the operator")
        self.assertTrue(bridge.emergency_latched)
        self.assertFalse(bridge.status()["connected"])
        self.assertIn("quittiert", bridge.clear_emergency())
        self.assertFalse(sim.latched)
        self.assertTrue(bridge.status()["connected"])


if __name__ == "__main__":
    unittest.main()
