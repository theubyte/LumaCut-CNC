"""Runs every tests/ui/test_*.py in the real window, each against its own fresh simulator.
    python tests/ui/run_all.py [exe] [test-name ...]
Each test module defines run(app) and may set USES_SIM = False or SIM_ARGS = [...].
"""
import importlib
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from driver import App  # noqa: E402


def main():
    args = sys.argv[1:]
    exe = args.pop(0) if args and args[0].lower().endswith(".exe") else None
    names = [p.stem for p in sorted(HERE.glob("test_*.py")) if not args or p.stem in args or p.stem.removeprefix("test_") in args]
    failed = []
    port = 8120
    for name in names:
        mod = importlib.import_module(name)
        port += 1
        sim = None
        url = None
        if getattr(mod, "USES_SIM", True):
            sim = subprocess.Popen([sys.executable, str(ROOT / "tools" / "sim_pi.py"), "--port", str(port), *getattr(mod, "SIM_ARGS", [])],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**__import__("os").environ, "PYTHONUTF8": "1"})
            time.sleep(5)
            url = f"http://127.0.0.1:{port}"
        app = None
        try:
            app = App(exe=exe, port=port + 1000, pi_url=url, env=getattr(mod, "ENV", None))
            app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=30)
            mod.run(app)
            print(f"OK    {name}", flush=True)
        except Exception:
            failed.append(name)
            print(f"FEHL  {name}\n{traceback.format_exc()}", flush=True)
            if app:
                try:
                    app.shot(ROOT / "build" / "shots" / f"fehler-{name}.png")
                except Exception:
                    pass
        finally:
            if app:
                app.close()
            if sim:
                # The venv python is a launcher: kill the whole tree, or the old simulator keeps the port.
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(sim.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"FEHLER in: {', '.join(failed)}" if failed else f"Alle {len(names)} Prüfungen grün", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
