"""Vorab-Check gegen den echten Pi: nichts fährt, nichts lasert, nichts wird geändert.

Die App spricht nur mit einer Sperre auf 127.0.0.1. Sie reicht ausschließlich GET auf einer festen Liste
an den Pi durch, alles andere beantwortet sie selbst mit 403 und notiert es. Nicht auf der Liste:
/api/backup (enthält Einstellungen, die hier niemand braucht) und /api/camera/snapshot (schaltet die LEDs ein).

    python tools/pi_readonly_check.py [--pi http://192.168.2.89:8080] [--exe Pfad\\LumaCutStudio.exe] [--shots Ordner]

Die App wird nur durch die Ansichten geführt, es wird kein Bedienelement für die Maschine geklickt.
Ende mit Code 0, wenn die App alle Werte richtig zeigt und nichts Schreibendes versucht hat.
"""
import argparse
import collections
import json
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "ui"))
from driver import App  # noqa: E402

ALLOWED = [re.compile(p) for p in (
    r"/api/status", r"/api/system", r"/api/materials", r"/api/bedmap", r"/api/matcal",
    r"/api/camera/settings", r"/api/camera/calibration",
    r"/api/jobs", r"/api/jobs/[^/]+/(content|geometry)",
    r"/api/workspace", r"/api/workspace/project", r"/api/workspace/scan",
    r"/api/projects", r"/api/projects/[^/]+",
)]
ACTIVE_JOB = {"homing", "probing", "focusing", "running", "finishing", "parking"}
VIEWS = ["material", "motiv", "start", "platine", "werkstatt", "optionen"]
MACHINE_TABS = ["steuerung", "kalibrieren", "system"]   # Kamera fehlt mit Absicht: jedes Bild schaltet die LEDs ein


class Gate:
    def __init__(self, pi):
        self.pi = pi.rstrip("/")
        self.passed = collections.Counter()
        self.refused = collections.Counter()
        self.failed = collections.Counter()
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, code, body=b"{}", kind="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def refuse(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                gate.refused[f"{self.command} {self.path.split('?')[0]}"] += 1
                self.answer(403, b'{"error":"Vorab-Check: nur lesen"}')

            def do_GET(self):
                path = self.path.split("?")[0]
                if not any(p.fullmatch(path) for p in ALLOWED):
                    self.refuse()
                    return
                try:
                    with urllib.request.urlopen(gate.pi + self.path, timeout=10) as r:
                        body, code, kind = r.read(), r.status, r.headers.get("Content-Type", "application/json")
                except urllib.error.HTTPError as e:
                    body, code, kind = e.read(), e.code, e.headers.get("Content-Type", "application/json")
                except OSError as e:
                    gate.failed[f"{path}: {e}"] += 1
                    self.answer(502, b'{"error":"Pi nicht erreichbar"}')
                    return
                gate.passed[f"{path} [{code}]"] += 1
                self.answer(code, body, kind)

            do_POST = do_PUT = do_DELETE = do_PATCH = refuse

        self.server = ThreadingHTTPServer(("127.0.0.1", 9582), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def read_pi(pi, path):
    with urllib.request.urlopen(pi + path, timeout=8) as r:
        return json.load(r)


def de(v):
    return f"{v:.1f}".replace(".", ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", default="http://192.168.2.89:8080")
    ap.add_argument("--exe")
    ap.add_argument("--shots", default=str(ROOT / "build" / "shots" / "pi-check"))
    args = ap.parse_args()
    pi = args.pi.rstrip("/")
    problems = []

    def check(what, ok, detail=""):
        print(("OK    " if ok else "FEHL  ") + what + (f"  ({detail})" if detail else ""), flush=True)
        if not ok:
            problems.append(what)

    before = read_pi(pi, "/api/status")
    for _ in range(10):   # direkt nach dem Dienststart kennt der Pi die Position kurz nicht
        if before["position"]:
            break
        time.sleep(1)
        before = read_pi(pi, "/api/status")
    if before["job"]["state"] in ACTIVE_JOB or before["frame"]["state"] not in ("idle", "") or before.get("busy"):
        print("Die Maschine arbeitet gerade. Kein Check, später noch einmal.")
        return 2
    print(f"Pi: {before.get('identity')}  Besitzer {before.get('owner')}  referenziert {before.get('homed')}", flush=True)
    system = read_pi(pi, "/api/system")
    print(f"Pi-Software: {system.get('software_commit')} vom {system.get('software_date')}", flush=True)

    gate = Gate(pi)
    shots = Path(args.shots)
    # Mit Abgleich: Die App holt das gemeinsame Projekt, ein Sendeversuch landet an der Sperre.
    app = App(exe=args.exe, port=9581, pi_url=gate.url, env={"LUMACUT_SYNC": "1", "LUMACUT_AUTOSAVE_DIR": tempfile.mkdtemp(prefix="lumacut-check-")})
    try:
        app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=30)
        app.wait(lambda: app.get("status-url", "text") != "getrennt", timeout=15)
        check("App verbunden", True, app.get("conn-chip", "text"))
        rev = before["sync"]["project"]
        if rev > 0:
            app.wait(lambda: app.invoke("sync-api", "baseRevision") == rev, timeout=20)
            check("Gemeinsames Projekt geladen", True, f"Revision {rev}, {app.get('projectTitle', 'text')}")
        app.click("nav-maschine")
        time.sleep(0.4)
        for tab in MACHINE_TABS:
            app.click(f"m-tab-{tab}")
            time.sleep(2.0)
            app.shot(shots / f"maschine-{tab}.png")
        app.click("m-tab-steuerung")
        time.sleep(1.5)

        st = read_pi(pi, "/api/status")
        travel_x = st["config"]["travels"]["x"]
        px, py, pz = st["position"]
        want = f"X {de(travel_x - px)}  Y {de(py)}  Z {de(pz)}"
        shown = app.get("status-pos", "text")
        check("Position wie am Pi (Arbeitskoordinaten)", shown.replace(" ", "")[:8] == want.replace(" ", "")[:8] or shown == want, f"App {shown} / Pi {want}")
        head = app.get("m-headline", "text")
        check("Kopfzeile passt zur Referenz", (head == "Nicht referenziert") == (not st["homed"]), head)
        check("Zustand wie am Pi", app.get("status-state", "text") == st["state"], st["state"])
        if not st["homed"]:
            lock = app.get("m-park", "lock")
            check("Parken ohne Referenz gesperrt", bool(lock), lock)

        for view in VIEWS:
            app.click(f"nav-{view}")
            time.sleep(2.0)
            app.shot(shots / f"{view}.png")
        time.sleep(3)   # Zeit für einen Abgleich, falls die App einen schicken wollte
    finally:
        app.close()

    after = read_pi(pi, "/api/status")
    check("Keine Schreibversuche der App", not gate.refused, "; ".join(f"{k} ×{v}" for k, v in gate.refused.items()))
    check("Alle Lesezugriffe beantwortet", not gate.failed, "; ".join(gate.failed))
    errors = {k: v for k, v in gate.passed.items() if not k.endswith("[200]")}
    check("Pi hat keinen Lesezugriff abgelehnt", not errors, str(errors) if errors else "")
    check("Position am Pi unverändert", after["position"] == before["position"], f"{before['position']} / {after['position']}")
    check("Licht und Abluft unverändert", (after["lights"], after["exhaust"]) == (before["lights"], before["exhaust"]))
    check("Projektstand am Pi unverändert", after.get("sync") == before.get("sync"), str(after.get("sync")))
    print("\nDurchgereicht: " + ", ".join(f"{k} ×{v}" for k, v in sorted(gate.passed.items())))
    print(f"Bilder: {shots}")
    print("FEHLER: " + ", ".join(problems) if problems else "Alles in Ordnung.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
