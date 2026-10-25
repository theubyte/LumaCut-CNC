"""Pi update regression checks without operating a real machine."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "pi400" / "update.sh"


class PiUpdaterTests(unittest.TestCase):
    def test_shell_syntax(self):
        result = subprocess.run(["bash", "-n", str(UPDATER)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_silent_update_skips_or_unreviewed_reset(self):
        source = UPDATER.read_text(encoding="utf-8")
        self.assertIn('MODE=${1:-update}', source)
        self.assertIn('LUMACUT_HTTP:-8080', source)
        self.assertIn('safe_state "$response"', source)
        self.assertIn('die "LightBurn schließen', source)
        self.assertIn('https://github.com/theubyte/LumaCut-CNC.git', source)
        self.assertIn('GIT_TERMINAL_PROMPT=0 git_lumacut fetch', source)
        self.assertIn('git_lumacut merge --ff-only', source)
        self.assertIn('git_lumacut diff --quiet', source)
        self.assertIn('systemctl start "$SERVICE"', source)
        self.assertIn('SERVICE=lumacut-marlin.service', source)
        self.assertNotIn('flock -n 9 || exit 0', source)
        self.assertNotIn('idle || exit 0', source)
        self.assertNotIn('fetch --quiet origin main', source)

    def test_updater_does_not_flash_controller(self):
        source = UPDATER.read_text(encoding="utf-8")
        self.assertNotIn("stm32flash ", source)
        self.assertNotIn("pio run -t upload", source)
        self.assertIn('SKR-Firmware wird nicht automatisch aktualisiert', source)


if __name__ == "__main__":
    unittest.main()
