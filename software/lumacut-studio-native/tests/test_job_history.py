"""Auftragsverlauf und „G-Code speichern…“."""

from pathlib import Path

from _pi_guard import pi_check
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.model import Geometry, Shape
from lumacut_job.history import JobHistory
from lumacut_job.history_qt import HistoryDialog, attach_history

G = "M3 I\nG0 X1 Y1\nG1 X2 Y2 F600 S10\nM5\n"


def test_record_order_limit_and_corrupt_index(tmp_path):
    h = JobHistory(tmp_path, max_entries=3)
    for i in range(5):
        h.record(f"teil {i}/x.gcode", G + f"; {i}\n", "1 min", now=1_700_000_000 + i)
    es = h.entries()
    assert [e.name for e in es] == ["x.gcode"] * 3
    assert [h.load(e).splitlines()[-1] for e in es] == ["; 4", "; 3", "; 2"]
    assert len([p for p in tmp_path.iterdir() if p.suffix == ".gcode"]) == 3
    assert all("/" not in e.file and e.file.endswith(".gcode") for e in es)
    # gleiche Sekunde -> eindeutige Dateien
    a = h.record("a.nc", G, now=1_800_000_000)
    b = h.record("a.nc", G, now=1_800_000_000)
    assert a.file != b.file and a.file.endswith(".nc")
    h.remove(b)
    assert b.file not in {e.file for e in h.entries()} and not (tmp_path / b.file).exists()
    (tmp_path / "index.json").write_text("{kaputt", encoding="utf-8")
    assert h.entries() == []
    h.record("neu.gcode", G)
    assert [e.name for e in h.entries()] == ["neu.gcode"]


class FakePanel:
    def __init__(self, connected=True):
        self._client = object() if connected else None
        self.sent = []

    def send_gcode(self, name, gcode, start=False):
        self.sent.append((name, gcode, start))


def test_attach_records_only_when_connected(tmp_path, qapp):
    h = JobHistory(tmp_path)
    p = FakePanel(connected=False)
    attach_history(p, h)
    p.send_gcode("a.gcode", G)
    assert p.sent and h.entries() == []
    p._client = object()
    p.send_gcode("b.gcode", G, start=True)
    assert p.sent[-1] == ("b.gcode", G, True)
    assert [e.name for e in h.entries()] == ["b.gcode"]


def test_dialog_resend_save_remove(tmp_path, qapp):
    h = JobHistory(tmp_path / "h")
    h.record("eins.gcode", G, now=1)
    h.record("zwei.gcode", G + "; 2\n", now=2)
    sent = []
    dlg = HistoryDialog(h, lambda n, g: sent.append((n, g)))
    assert dlg.list.count() == 2 and dlg.current().name == "zwei.gcode"
    assert dlg.resend() and sent == [("zwei.gcode", G + "; 2\n")]
    out = dlg.save(str(tmp_path / "out.gcode"))
    assert Path(out).read_text(encoding="utf-8") == G + "; 2\n"
    assert dlg.remove(confirm=False) and dlg.list.count() == 1
    assert dlg.remove(confirm=False)
    assert dlg.current() is None and not dlg.resend_btn.isEnabled()
    dlg.close()


def test_job_tools_save_and_history(tmp_path, qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        tools = win.job_tools
        tools.history = JobHistory(tmp_path / "h")
        doc = win.canvas.document
        assert tools.save_gcode(str(tmp_path / "leer.gcode")) == ""  # leeres Design
        win.canvas.undo_stack.push(AddShapesCommand(
            doc, [Shape("rect", Geometry(20, 20, 30, 30), doc.active_layer.id)], "Rechteck"))
        out = tools.save_gcode(str(tmp_path / "x.gcode"))
        pi_check(Path(out).read_text(encoding="utf-8"))
        dlg = tools.show_history(modal=False)
        assert dlg.current() is None
        dlg.close()
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
