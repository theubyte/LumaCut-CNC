"""USB enumeration after grblHAL->Marlin flash: no real hardware needed."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from marlin.usb_detect import port_candidates, locate_verified_marlin

ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    attempts = []
    def __init__(self, port):
        self.port = port
        self.lock = __import__("threading").RLock()
        self.attempts.append(port)
        self.closed = False
    def ensure_ready(self):
        if not self.port.endswith("ttyACM1"):
            raise RuntimeError("Geraet antwortet nicht als LumaCut Marlin")
    def _close_locked(self):
        self.closed = True


class USBDetectTests(unittest.TestCase):
    def setUp(self):
        FakeTransport.attempts.clear()

    def test_stale_by_id_path_falls_back_to_new_marlin_acm(self):
        with tempfile.TemporaryDirectory() as root:
            dev = Path(root)
            (dev / "ttyACM1").touch()
            self.assertEqual(
                locate_verified_marlin(
                    "/dev/serial/by-id/usb-STMicroelectronics_old-grblhal",
                    device_root=dev, factory=FakeTransport),
                str(dev / "ttyACM1"))
            self.assertEqual(FakeTransport.attempts, [str(dev / "ttyACM1")])

    def test_rejects_no_usb_devices_with_specific_diagnostic(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "Kein serielles SKR"):
                locate_verified_marlin("/dev/serial/by-id/missing",
                                       device_root=Path(root), factory=FakeTransport)

    def test_rejects_non_marlin_usb_without_overwriting_any_config(self):
        with tempfile.TemporaryDirectory() as root:
            dev = Path(root)
            (dev / "ttyUSB0").touch()
            with self.assertRaisesRegex(RuntimeError, "keine LumaCut-Marlin"):
                locate_verified_marlin("/dev/serial/by-id/missing",
                                       device_root=dev, factory=FakeTransport)

    def test_configured_port_first_when_still_present(self):
        with tempfile.TemporaryDirectory() as root:
            dev = Path(root)
            first = dev / "ttyACM1"
            first.touch()
            second = dev / "ttyACM2"
            second.touch()
            ports = port_candidates(str(first), device_root=dev)
            self.assertEqual(ports[0], str(first))
            self.assertEqual(ports.count(str(first)), 1)

    def test_installer_pins_verified_port_in_separate_file(self):
        install = (ROOT / "pi400/install.sh").read_text(encoding="utf-8")
        unit = (ROOT / "pi400/marlin/lumacut-marlin.service").read_text(encoding="utf-8")
        self.assertIn("python3 -m marlin.usb_detect", install)
        self.assertIn("/dev/serial/by-id", install)
        self.assertIn("PORT_ENV=/etc/lumacut/lumacut-marlin-port.env", install)
        self.assertIn("EnvironmentFile=-/etc/lumacut/lumacut-marlin-port.env", unit)
        self.assertNotIn("sed -i", install)
        # Installing never flashes the SKR.
        self.assertNotIn("M997", install)
        self.assertNotIn("/api/firmware", install)

    def test_installer_retires_old_grbl_service(self):
        install = (ROOT / "pi400/install.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl disable --now lumacut.service", install)
        self.assertIn("systemctl enable --now lumacut-marlin.service", install)
        result = subprocess.run(["bash", "-n", str(ROOT / "pi400/install.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
