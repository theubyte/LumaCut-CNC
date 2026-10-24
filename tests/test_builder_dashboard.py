"""Regression checks for the LumaCut Build Lab V2 frontend and API wiring.

Static checks run without the private Unraid container or access to real boards.
The CI workflow additionally runs Node.js syntax checking on dashboard.js.
"""
from pathlib import Path
import ast
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
BUILDER=ROOT/"builder"
APP=(BUILDER/"app.py").read_text(encoding="utf-8")
HTML=(BUILDER/"dashboard.html").read_text(encoding="utf-8")
JS=(BUILDER/"dashboard.js").read_text(encoding="utf-8")
CSS=(BUILDER/"dashboard.css").read_text(encoding="utf-8")
DOCKER=(BUILDER/"Dockerfile").read_text(encoding="utf-8")

class DashboardV2Tests(unittest.TestCase):
    def test_python_syntax(self):
        ast.parse(APP)

    def test_five_clear_primary_operations(self):
        actions=re.findall(r'data-action="([^"]+)"',HTML)
        self.assertEqual(actions,["complete","hmi","skr","flash","sd"])
        for target in ('lumacut_complete_suite_unverified',
                       'esp32_hmi_pro_unverified','stm32_hmi_bridge_unverified'):
            self.assertIn(target,JS)
            self.assertIn(target,APP)

    def test_progress_and_history(self):
        for key in ('STAGES={','WEIGHTS={','progress_info(meta)','eta_seconds',
                    'stage_started_utc','"stage_index"','/api/jobs'):
            self.assertIn(key,APP)
        for id in ('history-list','progress-fill','progress-value','progress-time',
                   'terminal-output','modal-root','modal-close'):
            self.assertIn('id="'+id+'"',HTML)
        self.assertIn('showFinish(job)',JS)
        self.assertIn('model.watch.add(result.id)',JS)

    def test_flash_and_sd_downloads(self):
        self.assertIn('"/api/jobs/<job_id>/sd-image"',APP)
        self.assertIn('download_name="firmware.bin"',APP)
        self.assertIn('window.showDirectoryPicker',JS)
        self.assertIn('window.isSecureContext',JS)
        self.assertIn('esp-web-install-button',JS)
        self.assertIn('Waveshare-HMI-Flash-Paket-Windows.zip',JS)

    def test_approved_skr_firmware_download_instead_of_disabled_banner(self):
        self.assertIn('"/api/updates/skr-firmware.bin"',APP)
        self.assertIn('"/api/updates/skr-firmware.bin",true',JS)
        self.assertIn('SKR-Update firmware.bin herunterladen',JS)
        self.assertNotIn('Firmwareinstallation auf dem SKR bleibt bis zur Bootloader-Prüfung deaktiviert.',JS)
        self.assertNotIn('"automatic_skr_flash_enabled":False',APP)

    def test_readonly_diagnostic_terminal(self):
        self.assertIn('terminalCommand(cmd)',JS)
        self.assertIn('Nur lesende Build-',JS)
        self.assertNotIn('shell=True',APP)
        self.assertNotIn('docker.sock',DOCKER)
        self.assertNotIn('subprocess.run(request',APP)

    def test_frontend_in_image(self):
        self.assertIn('dashboard.html dashboard.css dashboard.js',DOCKER)
        self.assertIn('href="/ui/dashboard.css"',HTML)
        self.assertIn('src="/ui/dashboard.js"',HTML)
        self.assertIn('@app.get("/ui/<asset>")',APP)
        self.assertIn('@app.get("/")',APP)
        self.assertIn('@media(max-width:720px)',CSS)

if __name__=="__main__":
    unittest.main()
