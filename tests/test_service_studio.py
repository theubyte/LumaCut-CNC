"""Safety regression tests for Pi 400 service access and pin assignment.

Tests intentionally do not command real motors, lasers or accessory outputs.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from lumacut.pins import (DEFAULT_ROLES, accessories_for_roles, manifest,
                         override_for_role, validate_roles)
from lumacut.service_auth import ServiceAuth


class PinMapTests(unittest.TestCase):
    def test_default_roles_match_grbl_status_accessories(self):
        data = accessories_for_roles({"lights": True, "exhaust": False},
                                     DEFAULT_ROLES)
        self.assertEqual(data, {"lights": True, "exhaust": False})
        self.assertEqual(override_for_role("lights", DEFAULT_ROLES), bytes((0xA1,)))
        self.assertEqual(override_for_role("exhaust", DEFAULT_ROLES), bytes((0xA0,)))

    def test_swapping_roles_changes_only_logical_mapping(self):
        roles = validate_roles({"lights": "M8", "exhaust": "M7"})
        self.assertEqual(accessories_for_roles(
            {"lights": True, "exhaust": False}, roles),
            {"lights": False, "exhaust": True})
        self.assertEqual(override_for_role("lights", roles), bytes((0xA0,)))

    def test_pc7_response_and_stale_default(self):
        from lumacut.core import Controller
        ctrl = Controller("/dev/null")
        self.assertIsNone(ctrl.status()["extra_outputs"]["PC7"])
        ctrl._read_response("[LCIO:PC7=1]")
        self.assertEqual(ctrl.status()["extra_outputs"]["PC7"], 1)
        ctrl._read_response("[LCIO:PC7=0]")
        self.assertEqual(ctrl.status()["extra_outputs"]["PC7"], 0)

    def test_custom_pc7_roles_validated(self):
        from lumacut.pins import validate_spare_config
        value = validate_spare_config(
            {"pin": "PC7", "role": "air_assist", "name": "Air Assist"})
        self.assertEqual(value["role"], "air_assist")
        for bad in ({"pin": "PC9", "role": "custom", "name": "Laser"},
                    {"pin": "PC7", "role": "stepper", "name": "Y"},
                    {"pin": "PC7", "role": "custom", "name": "x; M3 S1000"}):
            with self.assertRaises(ValueError):
                validate_spare_config(bad)

    def test_identity_decode_is_from_real_grbl_lines(self):
        from lumacut.core import Controller
        c = Controller("/dev/null")
        for line in ("[VER:1.1f.20261015:]",
                     "[FIRMWARE:grblHAL]",
                     "[BOARD:LumaCut SKR Mini MZ v1.0 EXPERIMENTAL]",
                     "[DRIVER:STM32F103RC@72MHz]"):
            c._read_response(line)
        self.assertEqual(c.status()["identity"]["firmware"], "grblHAL")
        self.assertIn("SKR Mini MZ", c.status()["identity"]["board"])

    def test_pin_conflicts_and_reserved_outputs_refused(self):
        for value in ({"lights": "M7", "exhaust": "M7"},
                      {"lights": "PC9", "exhaust": "M8"},
                      {"lights": "M7"},
                      {"lights": "M7", "exhaust": "M8", "laser": "PC9"}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_roles(value)
        pins = manifest(DEFAULT_ROLES)["pins"]
        for name in ("PA1", "PC9", "PC2", "PC10/PC11", "PA11/PA12"):
            pin = next(p for p in pins if p["pin"] == name)
            self.assertEqual(pin["availability"], "reserved")


class ServiceAuthTests(unittest.TestCase):
    def test_password_is_hashed_and_persistent(self):
        with tempfile.TemporaryDirectory() as path:
            gate = ServiceAuth(Path(path))
            self.assertTrue(gate.authenticate("lumaservice", "client"))
            text = (Path(path)/"service-auth.json").read_text()
            self.assertNotIn('"lumaservice"', text)
            gate2 = ServiceAuth(Path(path))
            self.assertTrue(gate2.authenticate("lumaservice", "client"))

    def test_failed_attempts_throttled(self):
        with tempfile.TemporaryDirectory() as path:
            gate = ServiceAuth(Path(path))
            for _ in range(5):
                self.assertFalse(gate.authenticate("incorrect", "client"))
            with self.assertRaises(PermissionError):
                gate.authenticate("lumaservice", "client")


class ServiceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Test suite's existing app test class may already have initialized
        # the Flask module; this test uses the same in-process application.
        import importlib
        os.environ.setdefault("LUMACUT_KEY", "unit-test-long-private-key")
        cls.env_dir = tempfile.TemporaryDirectory()
        os.environ.setdefault("LUMACUT_DATA", cls.env_dir.name)
        cls.app = importlib.import_module("lumacut.app").app

    @classmethod
    def tearDownClass(cls):
        cls.env_dir.cleanup()

    def test_pc7_api_denies_unauthenticated_mutations(self):
        client = self.app.test_client()
        headers = {"X-LumaCut-Key": os.environ["LUMACUT_KEY"]}
        self.assertEqual(client.post("/api/service/pc7/set", headers=headers,
                                     data={"value": "1"}).status_code, 403)
        self.assertEqual(client.post("/api/service/pc7/config", headers=headers,
                                     data={"pin": "PC7", "role": "custom",
                                           "name": "Pump"}).status_code, 403)

    def test_service_is_separately_password_gated(self):
        client = self.app.test_client()
        headers = {"X-LumaCut-Key": os.environ["LUMACUT_KEY"]}
        self.assertEqual(client.get("/service").status_code, 200)
        self.assertEqual(client.get("/api/service/pins", headers=headers).status_code, 403)
        self.assertEqual(client.post("/api/ui/setting", headers=headers,
                                     data={"id":"110","value":"1000"}).status_code, 403)
        self.assertEqual(client.post("/api/service/login", headers=headers,
                                     data={"password":"wrong"}).status_code, 403)
        answer=client.post("/api/service/login",headers=headers,
                           data={"password":"lumaservice"})
        self.assertEqual(answer.status_code,200)
        pins=client.get("/api/service/pins",headers=headers)
        self.assertEqual(pins.status_code,200)
        self.assertEqual(pins.get_json()["roles"],DEFAULT_ROLES)
        self.assertEqual(client.get("/api/service/diagnostics",
                                    headers=headers).status_code,200)
        self.assertEqual(client.post("/api/service/logout",
                                     headers=headers).status_code,200)
        self.assertEqual(client.get("/api/service/pins",headers=headers).status_code,403)


if __name__ == "__main__":
    unittest.main()
