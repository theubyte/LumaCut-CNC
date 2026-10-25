"""Materialdatenbank und Planer (Qt-frei)."""

import json
import math

import pytest

from lumacut_materials import load_db, plan_cut, plan_engrave, plan_relief
from lumacut_materials.build import settings_for
from lumacut_materials.db import DATA_PATH, MaterialError
from lumacut_materials.planner import (MAX_FOCUS_DROP_MM, MAX_PASSES, depth_per_pass,
                                       power_for_depth, speed_for_depth)


@pytest.fixture(scope="module")
def db():
    return load_db()


def test_database_structure(db):
    assert db.default_laser.id == "lasertree_lt80w_aa_pro"
    assert db.default_laser.optical_power_w == 10.0  # 80 W ist die elektrische Werbeangabe
    assert {l.optical_power_w for l in db.lasers} >= {5, 10, 20, 40}
    assert len(db.compatible()) >= 20 and len(db.incompatible()) >= 15
    for m in db.materials:
        assert m.sources and all(s.startswith("https://") for s in m.sources), m.id
        if not m.compatible:
            assert m.warnings and not m.operations()
    ids = {m.id for m in db.incompatible()}
    assert {"pvc_vinyl", "polycarbonate", "abs", "acrylic_clear", "ptfe"} <= ids
    wood = [m for m in db.compatible() if m.category == "wood" and m.can_cut]
    assert all({1, 2, 3, 5} <= set(m.thicknesses_mm) for m in wood)


def test_check_warns_for_unsafe(db):
    assert db.check("pvc_vinyl")[0].startswith("NICHT LASERN")
    assert any("Formaldehyd" in w for w in db.check("mdf"))
    with pytest.raises(MaterialError):
        plan_cut(db, "pvc_vinyl", 3)
    with pytest.raises(MaterialError):
        plan_cut(db, "anodized_aluminum", 1)  # nur Gravur
    with pytest.raises(MaterialError):
        plan_engrave(db, "slate", "deep")


def test_model_inverses_are_consistent(db):
    c, model = db.material("basswood_plywood").cut, db.model
    # Referenzpunkt reproduziert die Referenztiefe
    assert depth_per_pass(c, model, 10.0, 180) == pytest.approx(2.2)
    v = speed_for_depth(c, model, 7.0, 1.3)
    assert depth_per_pass(c, model, 7.0, v) == pytest.approx(1.3)
    p = power_for_depth(c, model, 400, 1.0)
    assert depth_per_pass(c, model, p, 400) == pytest.approx(1.0)
    e = db.material("basswood_solid").engrave
    v = speed_for_depth(e, model, 10.0, 0.2, 0.1)
    assert depth_per_pass(e, model, 10.0, v, 0.1) == pytest.approx(0.2)


@pytest.mark.parametrize("thickness", [1, 2, 3, 5, 8])
def test_cut_plan_covers_thickness(db, thickness):
    p = plan_cut(db, "basswood_plywood", thickness)
    assert p.laser_id == "lasertree_lt80w_aa_pro"
    assert p.passes * p.depth_per_pass_mm >= thickness * 1.09
    assert 1 <= p.speed_mm_min <= 6000 and 1 <= p.power_pct <= 100
    assert p.z_step_mm * (p.passes - 1) <= MAX_FOCUS_DROP_MM + 1e-9
    assert p.focus_offsets_mm[0] == 0 and len(p.focus_offsets_mm) == p.passes
    if p.passes > 1 and thickness >= 2:
        assert p.z_step_mm > 0


def test_more_power_needs_fewer_passes_or_is_faster(db):
    plans = [plan_cut(db, "mdf", 5, l) for l in ("diode_5w", "diode_10w", "diode_20w", "diode_40w")]
    for a, b in zip(plans, plans[1:]):
        assert (b.passes, -b.speed_mm_min) <= (a.passes, -a.speed_mm_min)
    assert plans[0].passes > plans[-1].passes


def test_speed_capped_at_machine_limit_reduces_power(db):
    p = plan_cut(db, "paper", 0.1, "diode_40w")
    assert p.speed_mm_min == 6000 and p.power_pct < 50


def test_too_thick_warns(db):
    p = plan_cut(db, "acrylic_black", 10)
    assert any("Maximum" in w for w in p.warnings)
    p = plan_cut(db, "hardwood", 40, "diode_5w")
    assert p.passes > MAX_PASSES and not p.feasible


def test_engrave_levels_get_deeper(db):
    plans = [plan_engrave(db, "basswood_solid", lv) for lv in ("shallow", "medium", "deep")]
    energy = [p.power_pct * p.passes / p.speed_mm_min for p in plans]
    assert energy == sorted(energy)
    assert all(p.line_interval_mm >= db.default_laser.spot_mm for p in plans)
    s = plan_engrave(db, "anodized_aluminum", "surface")
    assert s.passes == 1 and s.line_interval_mm == pytest.approx(0.08)


def test_relief_plan(db):
    p = plan_relief(db, "basswood_solid", 3.0)
    assert p.passes >= 2 and p.layer_depth_mm * p.passes == pytest.approx(3.0, abs=0.01)
    assert p.z_step_mm * (p.passes - 1) <= MAX_FOCUS_DROP_MM
    assert p.finish_speed_mm_min >= p.speed_mm_min
    assert any("Empfehlung" in w for w in plan_relief(db, "basswood_plywood", 3).warnings)
    with pytest.raises(MaterialError):
        plan_relief(db, "acrylic_black", 1)


def test_settings_table_in_sync_with_model(db):
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    for m in raw["materials"]:
        rows = settings_for(db, m["id"])
        assert m["settings"] == json.loads(json.dumps(rows)), \
            f"{m['id']}: python -m lumacut_materials.build ausführen"
    ply = db.material("basswood_plywood").settings
    assert {r["laser_power_w"] for r in ply} == {5.0, 10.0, 20.0, 40.0}
    assert {r["thickness_mm"] for r in ply if r["op"] == "cut"} >= {1, 2, 3, 5}


def test_limits_match_canvas_model():
    from lumacut_canvas import model
    assert MAX_PASSES == model.PASSES_RANGE[1]
    assert MAX_FOCUS_DROP_MM == model.MAX_FOCUS_DROP_MM
    from lumacut_materials import planner
    assert planner.MAX_Z_STEP_MM == model.Z_STEP_RANGE[1]
