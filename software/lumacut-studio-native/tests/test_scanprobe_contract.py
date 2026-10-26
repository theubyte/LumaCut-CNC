"""JSON-Vertrag Scan/Probe für Studio und spätere Android-App (Anforderungen 2026-10-26 §3)."""
from __future__ import annotations

import base64
import json

import pytest

from scanprobe import adapters, contract
from scanprobe.control import Progress, RunControl
from scanprobe.geometry import Rect
from scanprobe.workflow import ScanProbeWorkflow
from test_job_flow import GCODE, make


def test_scan_request_validation():
    r = contract.parse_scan_request({"camera": "pi", "bounds": [0, 0, 100, 80]})
    assert r.bounds == (0.0, 0.0, 100.0, 80.0) and r.overlap == 0.25
    assert contract.parse_scan_request({}).camera == "pi"
    assert contract.parse_scan_request(json.loads(json.dumps(r.to_dict()))) == r
    for bad in ([], {"camera": "usb"}, {"bounds": [0, 0, 10]}, {"bounds": [10, 0, 0, 10]},
                {"overlap": 0.9}):
        with pytest.raises(ValueError):
            contract.parse_scan_request(bad)


def test_job_request_validation():
    r = contract.parse_job_request({"name": "motiv.gcode", "gcode": GCODE})
    assert r.reuse_mesh
    assert contract.parse_job_request(json.loads(json.dumps(r.to_dict()))) == r
    for bad in ({"name": "../x.gcode", "gcode": GCODE}, {"name": "x.txt", "gcode": GCODE},
                {"name": "x.gcode", "gcode": "  "}, {"name": "x.gcode", "gcode": GCODE,
                                                      "reuse_mesh": "ja"}):
        with pytest.raises(ValueError):
            contract.parse_job_request(bad)


def test_job_events_follow_contract():
    flow, port, events, _ = make()
    res = flow.run(GCODE, "motiv.gcode")
    assert res.ok
    for e in events:
        assert contract.validate_message(e) == [], e
        assert list(e)[:len(contract.JOB_STATE_KEYS)] == list(contract.JOB_STATE_KEYS)
    out = res.to_dict()
    assert contract.validate_message(out) == []
    assert json.loads(json.dumps(out)) == out


def test_error_events_follow_contract():
    flow, port, events, _ = make(fail={"home": "kaputt"})
    res = flow.run(GCODE)
    assert contract.validate_message(events[-1]) == []
    assert events[-1]["error"]["code"] == "homing_failed"
    assert contract.validate_message(res.to_dict()) == []
    assert contract.validate_message(contract.error_message("emergency", "NOT-AUS")) == []
    assert contract.validate_message({"type": "job_state", "state": "fliegen"})


def test_scan_progress_and_result():
    p = contract.scan_progress(Progress("scan", 3, 12, "Kachel 3/12", 41.234))
    assert p == {"type": "scan_progress", "phase": "scan", "done": 3, "total": 12,
                 "progress": 0.25, "message": "Kachel 3/12", "eta_s": 41.2}
    assert contract.validate_message(p) == []
    hw = adapters.simulated_setup()
    wf = ScanProbeWorkflow(hw.machine, hw.camera, hw.probe, hw.calibration, settle_s=0.0)
    mosaic = wf.scan(Rect(60, 70, 200, 180))
    objs = wf.detect(mosaic)
    res = contract.scan_result(mosaic, objs, image=True)
    assert contract.validate_message(res) == []
    assert res["mosaic"]["format"] == "lumacut-scan-mosaic/1"
    assert base64.b64decode(res["image_png_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert json.loads(json.dumps(res))["objects"] == res["objects"]
    assert "image_png_base64" not in contract.scan_result(mosaic)


def test_endpoints_documented():
    import pathlib
    doc = pathlib.Path(__file__).resolve().parents[3] / "docs" / "SCAN_PROBE.md"
    text = doc.read_text(encoding="utf-8")
    for ep in contract.ENDPOINTS:
        assert ep in text, ep
    assert contract.CONTRACT in text
