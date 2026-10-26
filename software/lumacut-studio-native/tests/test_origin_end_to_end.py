"""Zero point and anchors end to end (Anforderungen 2026-10-26 §2.1/§2.3).

Studio canvas export -> Pi placement (real pi400/marlin/placement.py) ->
frame: the corner the user picks by what they *see* must land on the target,
for the current Pi (``coord_convention``) and an older one (wire_anchor
swaps left/right). Pure functions, no network, no hardware.

Machine: X0/Y0 = endstop corner top right (seen from the door), X grows to
the left, Y towards the door, work area X30-390 / Y30-370.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import placement as placing  # noqa: E402

from lumacut_canvas import workarea  # noqa: E402
from lumacut_canvas.export import job_layers  # noqa: E402
from lumacut_canvas.gcode import document_to_gcode  # noqa: E402
from lumacut_canvas.model import Document, Geometry, Shape  # noqa: E402
from lumacut_job.estimate import frame_gcode  # noqa: E402
from machine.client import (ANCHORS, COORD_CONVENTION, DEFAULT_ANCHOR,  # noqa: E402
                            wire_anchor)

CORNERS = ("tl", "tr", "bl", "br")
MIRRORED = bool(getattr(workarea, "ORIGIN_TOP_RIGHT", False))


def _doc(x=300.0, y=10.0, w=50.0, h=30.0):
    """A rectangle near the visible top-right corner of the canvas."""
    doc = Document()
    doc.add_shape(Shape("rect", Geometry(x, y, w, h), doc.active_layer_id))
    return doc


def _xy(lines):
    pts = []
    for line in lines:
        words = {}
        for tok in line.split():
            if tok[:1] in "XY":
                words[tok[0]] = float(tok[1:])
        if "X" in words and "Y" in words:
            pts.append((words["X"], words["Y"]))
    return pts


def _old_anchor_point(box, anchor):
    """Pi before 2026-10-26: "l" = small X (physically right)."""
    return (box.xmin if anchor[1] == "l" else box.xmax,
            box.ymin if anchor[0] == "t" else box.ymax)


def test_studio_and_pi_agree_on_conventions():
    assert placing.COORD_CONVENTION == COORD_CONVENTION
    assert tuple(placing.ANCHORS) == tuple(ANCHORS)
    assert placing.DEFAULT_ANCHOR == DEFAULT_ANCHOR == "tr"


def test_frame_matches_pi_job_bounds(qapp):
    doc = _doc()
    lines = document_to_gcode(doc).splitlines()
    _, powered = placing.scan(lines)
    pts = _xy(frame_gcode(job_layers(doc)).splitlines())
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert (min(xs), min(ys), max(xs), max(ys)) == pytest.approx(
        (powered.xmin, powered.ymin, powered.xmax, powered.ymax), abs=0.01)
    # inside the cut area, never in the safe zone
    assert powered.xmin >= 30 - 1e-6 and powered.ymin >= 30 - 1e-6
    assert powered.xmax <= 390 + 1e-6 and powered.ymax <= 370 + 1e-6


@pytest.mark.parametrize("anchor", CORNERS + ("center",))
def test_anchor_lands_on_target(qapp, anchor):
    """Placing at a user origin moves the visible corner onto it (like
    web.py make_placement) and the frame follows the same offset."""
    lines = document_to_gcode(_doc(100, 100, 40, 20)).splitlines()
    _, box = placing.scan(lines)
    target = (200.0, 150.0)
    ax, ay = placing.anchor_point(box, anchor)
    placed = placing.translate(lines, target[0] - ax, target[1] - ay)
    _, moved = placing.scan(placed)
    assert placing.anchor_point(moved, anchor) == pytest.approx(target)
    if anchor != "center":
        # "r" = small X (switch side), "t" = small Y (back, switch side)
        assert (target[0] == pytest.approx(moved.xmin)) == (anchor[1] == "r")
        assert (target[1] == pytest.approx(moved.ymin)) == (anchor[0] == "t")


def test_default_anchor_at_switch_corner(qapp):
    """Default "tr" at user origin (30, 30): motif starts at the endstop corner."""
    lines = document_to_gcode(_doc(100, 100, 40, 20)).splitlines()
    _, box = placing.scan(lines)
    ax, ay = placing.anchor_point(box, DEFAULT_ANCHOR)
    _, moved = placing.scan(placing.translate(lines, 30 - ax, 30 - ay))
    assert (moved.xmin, moved.ymin) == pytest.approx((30.0, 30.0))
    placing.check_extent(placing.translate(lines, 30 - ax, 30 - ay),
                         {"x": 390.0, "y": 370.0}, 30.0)


@pytest.mark.parametrize("anchor", CORNERS)
def test_old_pi_gets_the_same_physical_corner(anchor):
    box = placing.Box(100.0, 50.0, 140.0, 70.0)
    new = placing.anchor_point(box, wire_anchor(anchor, COORD_CONVENTION))
    old = _old_anchor_point(box, wire_anchor(anchor, None))
    assert new == old


@pytest.mark.skipif(not MIRRORED, reason="Canvas §2.3 (ORIGIN_TOP_RIGHT) noch nicht auf main")
def test_visible_top_right_is_near_switch_corner(qapp):
    """§2.3: the canvas shows the bed as seen from the door, so a motif at
    the canvas' top-right corner ends up next to X0/Y0 (machine X30/Y30)."""
    _, box = placing.scan(document_to_gcode(_doc(310, 0, 50, 30)).splitlines())
    assert (box.xmin, box.ymin) == pytest.approx((30.0, 30.0), abs=0.5)
    assert box.xmax == pytest.approx(80.0, abs=0.5)
