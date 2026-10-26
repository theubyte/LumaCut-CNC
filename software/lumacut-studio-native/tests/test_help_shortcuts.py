"""Hilfe › Tastenkürzel (F1)."""

from lumacut_job.help_qt import FIXED_ENTRIES, collect_shortcuts


def test_shortcut_overview_lists_window_actions(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        assert win.help_menu.shortcuts_action.shortcut().toString() == "F1"
        assert win.menuBar().actions()[-1].text() == "&Hilfe"
        rows = collect_shortcuts(win)
        keys = {name: k for name, k, _ in rows}
        assert "Schnittoptionen…" in keys and keys["Schnittoptionen…"]
        assert "Rahmen" in keys
        assert any(n.startswith("Tastenkürzel") for n in keys)
        assert all(name in keys for name, _, _ in FIXED_ENTRIES)
        assert len(rows) == len({(n, k) for n, k, _ in rows})
        dlg = win.help_menu.show_shortcuts(modal=False)
        assert dlg.table.rowCount() == len(rows)
        assert 0 < dlg.apply_filter("rahmen") < len(rows)
        assert dlg.apply_filter("") == len(rows)
        dlg.close()
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
