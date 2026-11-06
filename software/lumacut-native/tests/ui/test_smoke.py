"""The window starts, the GPU draws, every area opens."""
import time

USES_SIM = False


def run(app):
    s = app.stats()
    assert s["api"] in (4, 5), f"Grafik-API ist nicht Direct3D: {s['api']}"  # QSGRendererInterface: 4 = D3D11, 5 = D3D12
    app.click("nav-start")
    time.sleep(0.3)
    assert app.invoke("gpuProbe", "benchmark", 1000000) == 1000000
    time.sleep(1.5)
    app.stats()
    time.sleep(2)
    print("Bilder/s bei 1 Mio. Segmenten:", round(app.stats()["fps"]))
    app.shot("build/shots/smoke-gpu.png")
    for key in ("material", "motiv", "platine", "werkstatt", "maschine", "optionen"):
        app.click(f"nav-{key}")
        time.sleep(0.1)
    app.shot("build/shots/smoke.png")
