"""Without LUMACUT_PI_URL a test run sends nothing into the network, and every view stays usable and says why."""
import subprocess
import time

USES_SIM = False


def run(app):
    time.sleep(1.5)
    assert app.invoke("shell", "piUrl") == ""
    assert app.get("conn-chip", "text") == "Pi nicht erreichbar"
    assert app.get("status-url", "text") == "getrennt"
    app.click("nav-maschine"); time.sleep(0.3)
    app.click("m-tab-steuerung"); time.sleep(0.2)
    assert app.get("m-headline", "text") == "Pi nicht erreichbar"
    assert app.get("m-home", "lock").startswith("Pi nicht erreichbar")
    app.click("estop"); time.sleep(0.3)   # NOT-AUS without a machine: says it was not confirmed
    assert "nicht bestätigt" in app.invoke("shell", "lastToast")
    for tab in ("kamera", "kalibrieren", "system"):
        app.click(f"m-tab-{tab}"); time.sleep(0.2)
    app.click("m-tab-steuerung")
    app.click("nav-material"); time.sleep(0.3)
    assert app.get("mt-new", "enabled") is False
    app.click("nav-optionen"); time.sleep(0.2)
    # Typing the real machine's address changes nothing: test runs only reach this PC.
    app.click("o-test"); time.sleep(0.5)
    assert "Testlauf" in app.get("o-check", "text")
    # No connection of this process leads anywhere but the driver.
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="oem", errors="replace").stdout
    pid = str(app.proc.pid)
    remote = [l.split()[2] for l in out.splitlines() if l.strip().endswith(pid) and len(l.split()) >= 5 and l.split()[3] == "ESTABLISHED"]
    assert all(r.startswith("127.0.0.1:") for r in remote), remote
