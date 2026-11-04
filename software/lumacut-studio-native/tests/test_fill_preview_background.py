"""Canvas fill preview with scan offset: planner in a background thread, cancellable."""

from __future__ import annotations

import threading
import time

import pytest

from test_fill_preview_scan_offset import _assert_preview_is_gcode, _preview_segments
from test_scan_offset import _doc, _table


@pytest.fixture(autouse=True)
def _restore_active_table():
    from lumacut_canvas import fill_preview
    from lumacut_job import scan_offset
    old = scan_offset.active_table()
    old_bg = fill_preview.BACKGROUND
    scan_offset._PREVIEW_CACHE.clear()
    yield
    scan_offset.set_active_table(old)
    scan_offset._PREVIEW_CACHE.clear()
    fill_preview.BACKGROUND = old_bg


def _grid(n=40, speed=3000):
    return _doc(tuple((10 + (i % 10) * 12, 10 + (i // 10) * 12, 8, 6) for i in range(n)),
                speed=speed)


def _plain(doc):
    from lumacut_canvas.export import layer_fill_blocks
    return [seg for layer in doc.layers if layer.visible and layer.fill_mode != "none"
            for _ids, segs in layer_fill_blocks(doc, layer) for seg in segs]


def _shifted(doc):
    from lumacut_job.scan_offset import preview_fill_lines
    return [seg for layer in doc.layers for seg in preview_fill_lines(doc).get(layer.id, [])]


def _same(a, b, tol=1e-9):
    return len(a) == len(b) and all(abs(p - q) <= tol for s, t in zip(a, b)
                                    for u, v in zip(s, t) for p, q in zip(u, v))


def _editor(doc):
    from lumacut_canvas.editor import CanvasEditor
    return CanvasEditor(doc)


def _spin(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    return cond()


# --- planner hook ---------------------------------------------------------------------------
def test_planner_should_stop_cancels_and_none_changes_nothing():
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import PlanCancelled, optimize_layers
    layers = job_layers(_grid())
    assert repr(optimize_layers(layers)) == repr(optimize_layers(layers, should_stop=None))
    assert repr(optimize_layers(layers)) == repr(optimize_layers(layers, should_stop=lambda: False))
    with pytest.raises(PlanCancelled):
        optimize_layers(layers, should_stop=lambda: True)
    calls = []

    def later():                        # stops in the middle of the fill ordering
        calls.append(1)
        return len(calls) > 5
    with pytest.raises(PlanCancelled):
        optimize_layers(layers, should_stop=later)
    assert len(calls) == 6


def test_block_and_polyline_ordering_poll_should_stop():
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import (PlanCancelled, improve_fill_block_order,
                                     order_fill_blocks_nearest, order_polylines)
    doc = _grid()
    doc.update_layer(doc.layers[0].id, hatch_outline=True)
    layer = job_layers(doc)[0]
    stop = lambda: True  # noqa: E731
    with pytest.raises(PlanCancelled):
        order_fill_blocks_nearest(layer.fills, (0, 0), should_stop=stop)
    nn = order_fill_blocks_nearest(layer.fills, (0, 0))
    with pytest.raises(PlanCancelled):
        improve_fill_block_order(nn, (0, 0), should_stop=stop)
    with pytest.raises(PlanCancelled):
        order_polylines(layer.polylines, (0, 0), should_stop=stop)
    assert order_polylines(layer.polylines, (0, 0), should_stop=lambda: False) == \
        order_polylines(layer.polylines, (0, 0))


def test_request_returns_none_cached_dict_or_job():
    from lumacut_job import scan_offset as so
    doc = _grid(4)
    assert so.preview_fill_request(doc, None) is None
    assert so.preview_fill_request(doc, _table((3000, 0.0))) is None
    job = so.preview_fill_request(doc, _table((3000, 0.4)))
    assert isinstance(job, so.FillPreviewJob)
    lines = job.run()
    cached = so.preview_fill_request(doc, _table((3000, 0.4)))
    assert isinstance(cached, dict) and cached == lines
    cached[doc.layers[0].id].clear()                      # callers get copies
    assert so.preview_fill_request(doc, _table((3000, 0.4)))[doc.layers[0].id]
    assert so.preview_fill_lines(doc, _table((3000, 0.4))) == lines
    _assert_preview_is_gcode(doc, _table((3000, 0.4)))


def test_job_runs_in_a_worker_thread_with_plain_data():
    from lumacut_job import scan_offset as so
    doc = _grid(6)
    job = so.preview_fill_request(doc, _table((3000, 0.3)))
    out = {}
    t = threading.Thread(target=lambda: out.update(r=job.run()))
    t.start()
    t.join(30)
    assert out["r"] == so.preview_fill_lines(doc, _table((3000, 0.3)))


# --- canvas widget --------------------------------------------------------------------------
def test_rebuild_starts_background_run_and_draws_plain_geometry_meanwhile(qapp, monkeypatch):
    from lumacut_job import scan_offset as so
    from lumacut_job.scan_offset import set_active_table
    doc = _grid()
    ed = _editor(doc)
    fp = ed.fill_preview
    set_active_table(_table((3000, 0.4)))
    threads = []
    orig = so.FillPreviewJob.run

    def spy(self, should_stop=None):
        threads.append(threading.current_thread())
        return orig(self, should_stop)
    monkeypatch.setattr(so.FillPreviewJob, "run", spy)
    runs = fp.background_runs
    fp.rebuild()
    assert fp.busy() and fp.scan_offset_pending and not fp.scan_offset_applied
    assert fp.background_runs == runs + 1
    assert _same(_preview_segments(ed), _plain(doc))          # plain geometry until it is done
    assert fp.wait()
    assert not fp.busy() and not fp.scan_offset_pending and fp.scan_offset_applied
    assert threads and threads[0] is not threading.main_thread()
    assert _same(_preview_segments(ed), _shifted(doc))        # preview == output
    _assert_preview_is_gcode(doc, _table((3000, 0.4)))
    # unchanged job: cached plan, drawn at once without a new run
    runs = fp.background_runs
    fp.rebuild()
    assert not fp.busy() and fp.scan_offset_applied and fp.background_runs == runs


def test_poll_timer_collects_result_in_the_event_loop(qapp):
    from lumacut_job.scan_offset import set_active_table
    doc = _grid()
    ed = _editor(doc)
    fp = ed.fill_preview
    set_active_table(_table((3000, 0.4)))
    fp.rebuild()
    assert fp.busy()
    assert _spin(qapp, lambda: not fp.busy())                # no explicit wait()
    assert fp.scan_offset_applied and _same(_preview_segments(ed), _shifted(doc))


def test_document_edit_debounces_and_shows_the_new_plan(qapp):
    from lumacut_canvas.model import Geometry, Shape
    from lumacut_job.scan_offset import set_active_table
    doc = _grid(10)
    set_active_table(_table((3000, 0.4)))
    ed = _editor(doc)
    fp = ed.fill_preview
    assert fp.wait() and fp.scan_offset_applied
    doc.add_shape(Shape("rect", Geometry(150, 150, 20, 10), doc.layers[0].id))
    assert _spin(qapp, lambda: not fp._timer.isActive() and not fp.busy()
                 and fp.scan_offset_applied)
    assert _same(_preview_segments(ed), _shifted(doc))
    _assert_preview_is_gcode(doc, _table((3000, 0.4)))


def _blocking_run(started, release):
    """Fake ``FillPreviewJob.run`` that waits for ``release`` and honours ``should_stop``."""
    from lumacut_job.planner import PlanCancelled

    def run(self, should_stop=None):
        started.append(self)
        while not release.is_set():
            if should_stop is not None and should_stop():
                raise PlanCancelled()
            time.sleep(0.002)
        return {lid: [((1.0, 2.0), (3.0, 2.0))] for lid in {l.layer_id for l in self.layers}}
    return run


def test_edit_while_planning_cancels_the_running_worker(qapp, monkeypatch):
    from lumacut_canvas.model import Geometry, Shape
    from lumacut_job import scan_offset as so
    doc = _grid(10)
    so.set_active_table(_table((3000, 0.4)))
    started, release = [], threading.Event()
    monkeypatch.setattr(so.FillPreviewJob, "run", _blocking_run(started, release))
    ed = _editor(doc)
    fp = ed.fill_preview
    first = fp._worker
    assert first is not None and fp.scan_offset_pending
    doc.add_shape(Shape("rect", Geometry(150, 150, 20, 10), doc.layers[0].id))   # schedule()
    assert first.stop.is_set() and not fp.busy() and not fp.scan_offset_pending
    assert first.done.wait(5) and first.cancelled and first.result is None
    fp.rebuild()                                           # debounce over
    second = fp._worker
    assert second is not None and second is not first
    release.set()
    assert fp.wait() and fp.scan_offset_applied and fp.line_count() == 1
    assert len(started) == 2


def test_stale_result_is_never_drawn(qapp, monkeypatch):
    from lumacut_job import scan_offset as so
    doc = _grid(4)
    so.set_active_table(_table((3000, 0.4)))
    ed = _editor(doc)
    fp = ed.fill_preview
    assert fp.wait()
    so._PREVIEW_CACHE.clear()
    started, release = [], threading.Event()
    monkeypatch.setattr(so.FillPreviewJob, "run", _blocking_run(started, release))
    fp.rebuild()
    old = fp._worker
    old.stop = threading.Event()          # pretend it cannot be stopped in time
    fp._generation += 1                   # a newer state exists
    release.set()
    assert old.done.wait(5) and old.result is not None
    before = _preview_segments(ed)
    fp._collect()
    assert _preview_segments(ed) == before and not fp.scan_offset_applied


def test_worker_error_keeps_plain_geometry(qapp, monkeypatch):
    from lumacut_job import scan_offset as so
    doc = _grid(4)
    so.set_active_table(_table((3000, 0.4)))
    ed = _editor(doc)
    fp = ed.fill_preview
    assert fp.wait()
    for exc in (RuntimeError("kaputt"), ValueError("zu viele Linien")):
        so._PREVIEW_CACHE.clear()

        def boom(self, should_stop=None, exc=exc):
            raise exc
        monkeypatch.setattr(so.FillPreviewJob, "run", boom)
        fp.rebuild()
        assert fp.wait()
        assert not fp.scan_offset_applied and _same(_preview_segments(ed), _plain(doc))


def test_synchronous_mode_and_table_off(qapp):
    from lumacut_canvas import fill_preview
    from lumacut_job.scan_offset import set_active_table
    doc = _grid(6)
    ed = _editor(doc)
    fp = ed.fill_preview
    fill_preview.BACKGROUND = False
    set_active_table(_table((3000, 0.4)))
    fp.rebuild()
    assert not fp.busy() and fp.scan_offset_applied
    assert _same(_preview_segments(ed), _shifted(doc))
    fill_preview.BACKGROUND = True
    set_active_table(None)
    runs = fp.background_runs
    fp.rebuild()
    assert not fp.busy() and fp.background_runs == runs and not fp.scan_offset_applied
    assert _same(_preview_segments(ed), _plain(doc))
    assert fp.wait()


def test_large_job_rebuild_does_not_block_the_gui_thread(qapp):
    """1500 hatched objects: the planner (≈1 s) runs in the worker, rebuild returns early."""
    from lumacut_job.scan_offset import set_active_table
    doc = _doc(tuple((5 + (i % 50) * 7.5, 5 + (i // 50) * 9, 5, 6) for i in range(1500)),
               speed=3000, line_interval_mm=0.5)
    ed = _editor(doc)
    fp = ed.fill_preview
    set_active_table(_table((3000, 0.3)))
    t0 = time.perf_counter()
    fp.rebuild()
    gui = time.perf_counter() - t0
    assert fp.busy()
    t1 = time.perf_counter()
    assert fp.wait(60)
    total = gui + time.perf_counter() - t1
    assert fp.scan_offset_applied
    assert gui < total            # the expensive part happened off the GUI thread
