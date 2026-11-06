"""Progress strip during a job, Abbrechen without a go, locks while it runs; update check against a local stand-in for GitHub."""
import hashlib
import http.server
import json
import threading
import time
import urllib.parse
import urllib.request

SIM_ARGS = ["--slow"]
UPDATE_PORT = 8202
ENV = {"LUMACUT_UPDATE_API": f"http://127.0.0.1:{UPDATE_PORT}"}
MSI = b"not a real installer"
GOOD_SUM = hashlib.sha256(MSI).hexdigest()
sums = {"sha256": "0" * 64}


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        base = f"http://127.0.0.1:{UPDATE_PORT}"
        if self.path.startswith("/releases"):
            body = json.dumps([
                {"tag_name": "android-99", "assets": []},
                {"tag_name": "windows-99.1.0", "body": "Neu: alles.", "assets": [
                    {"name": "LumaCut-Studio.msi", "browser_download_url": base + "/msi"},
                    {"name": "LumaCut-Studio.json", "browser_download_url": base + "/meta"}]}]).encode()
        elif self.path == "/meta":
            body = json.dumps({"size": len(MSI), "sha256": sums["sha256"]}).encode()
        elif self.path == "/msi":
            body = MSI
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def post(url, path, data, ctype, method="POST"):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": ctype}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=60))


def run(app):
    app.click("nav-maschine"); time.sleep(0.3)
    app.click("m-tab-steuerung"); time.sleep(0.2)
    app.click("m-home"); time.sleep(0.2)
    app.click("go-confirm")
    app.wait(lambda: app.get("m-homed", "text") == "Ja", timeout=20)

    # The job itself comes from the outside here (the view that starts jobs belongs to Starten).
    lines = ["G90", "G0 X100 Y100"] + [f"G1 X{100 + i % 2 * 40} Y{100 + i} F600" for i in range(120)]
    boundary = "----t"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="t.gcode"\r\nContent-Type: text/plain\r\n\r\n' + "\n".join(lines) + f"\r\n--{boundary}--\r\n").encode()
    url = app.invoke("shell", "piUrl")
    post(url, "/api/upload", body, f"multipart/form-data; boundary={boundary}")
    post(url, "/api/workspace", json.dumps({"material": {"name": "Test", "thickness_mm": 3}}).encode(), "application/json", "PUT")
    threading.Thread(target=lambda: post(url, "/api/action", urllib.parse.urlencode({"op": "start", "name": "t.gcode"}).encode(), "application/x-www-form-urlencoded"), daemon=True).start()
    app.wait(lambda: any(i["name"] == "jobstrip" for i in app.tree()), timeout=15)
    assert app.get("conn-chip", "text") == "Auftrag läuft"
    assert app.get("job-phase", "text") != ""
    assert app.get("m-home", "lock").startswith("Auftrag")
    app.shot("build/shots/test-job.png")
    app.click("job-abort")
    app.wait(lambda: not any(i["name"] == "jobstrip" for i in app.tree()), timeout=20)

    # Update: newest windows-* release is offered, a wrong checksum is thrown away, a right one passes (msiexec is never started in a test run).
    server = http.server.ThreadingHTTPServer(("127.0.0.1", UPDATE_PORT), FakeGitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        app.click("nav-optionen"); time.sleep(0.3)
        app.click("o-check-update")
        app.wait(lambda: any(i["name"] == "o-install" for i in app.tree()), timeout=10)
        assert "99.1.0" in app.get("o-update-version", "text")
        app.shot("build/shots/test-update.png")
        app.click("o-install"); time.sleep(0.2)
        app.click("confirm-ok")
        app.wait(lambda: "Prüfsumme stimmt nicht" in app.invoke("shell", "lastToast"), timeout=10)
        sums["sha256"] = GOOD_SUM
        app.click("o-check-update"); time.sleep(0.8)
        app.click("o-install"); time.sleep(0.2)
        app.click("confirm-ok"); time.sleep(0.8)
        assert app.invoke("shell", "updateState") == "verified"
    finally:
        server.shutdown()
