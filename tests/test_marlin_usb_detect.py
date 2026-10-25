"""USB enumeration after grblHAL->Marlin flash: no real hardware needed."""
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

    def test_activation_keeps_previous_usb_path_separate(self):
        activate = (ROOT / "pi400/marlin/activate.sh").read_text()
        unit = (ROOT / "pi400/marlin/lumacut-marlin.service").read_text()
        self.assertIn("python3 -m marlin.usb_detect", activate)
        self.assertIn("DETECTED_PORT=", activate)
        self.assertIn("lumacut-marlin-port.env", activate)
        self.assertIn("EnvironmentFile=-/etc/lumacut/lumacut-marlin-port.env", unit)
        self.assertNotIn('sed -i', activate)
        self.assertNotIn('flash', activate.split('DETECTED_PORT=')[1].split('cp "$ROOT')[0])


if __name__ == "__main__":
    unittest.main()
