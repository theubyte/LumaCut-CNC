"""Hauptfenster auf kleinen Bildschirmen (Surface Pro, 1024×600, 1280×720), offscreen."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea, QToolButton

from lumacut_canvas import fit, touch


def settle(qapp, rounds: int = 3) -> None:
    """Ereignisse abarbeiten *und* 0-ms-Timer feuern lassen: unter Windows
    laufen diese nicht zuverlässig in einem processEvents()-Durchgang."""
    for _ in range(rounds):
        qapp.processEvents()
        QTest.qWait(20)
    qapp.processEvents()


@pytest.fixture
def make_win(qapp, tmp_path, monkeypatch):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    wins = []

    def make(w, h):
        win = main.LumaCutStudio()
        win.resize(w, h)
        win.show()
        settle(qapp)
        wins.append(win)
        return win
    yield make
    for win in wins:
        win.canvas.undo_stack.setClean()
        win.close()


def _widest(area: QScrollArea) -> str:
    """Breiteste Kind-Widgets (Diagnose, falls ein Panel auf einem Runner zu breit ist).
    Effektives Layout-Minimum (minimumWidth hat Vorrang vor minimumSizeHint)."""
    from PySide6.QtWidgets import QApplication, QCheckBox, QWidget

    def eff(w):
        return w.minimumWidth() or w.minimumSizeHint().width()
    kids = [w for w in area.widget().findChildren(QWidget) if w.isVisibleTo(area.widget())]
    leaves = sorted((w for w in kids if not w.findChildren(QWidget)), key=lambda w: -eff(w))[:4]
    out = [f"{type(w).__name__}({w.objectName() or getattr(w, 'text', lambda: '')()!s:.20})"
           f"={eff(w)}/{w.minimumSizeHint().width()}" for w in leaves]
    for box in sorted(area.widget().findChildren(QCheckBox), key=lambda b: -b.minimumSizeHint().width())[:1]:
        f = box.font()
        out.append(f"check:min={box.minimumWidth()} adv={box.fontMetrics().horizontalAdvance(box.text())} "
                   f"pt={f.pointSizeF()} px={f.pixelSize()} fam={f.family()} "
                   f"style={QApplication.style().name()} mark={box.property(fit._COMPACT_MARK)}")
    return ", ".join(out)


def _not_clipped(area: QScrollArea) -> bool:
    content = area.widget()
    fits = content.minimumSizeHint().width() <= area.viewport().width()
    return fits or area.horizontalScrollBar().isVisible()


@pytest.mark.parametrize("size", [(1024, 600), (1280, 720), (1368, 912)])
def test_panels_fit_inside_small_windows(make_win, size):
    win = make_win(*size)
    assert win.width() == size[0]
    sp = win.splitter
    assert sum(sp.sizes()) + sp.handleWidth() * (sp.count() - 1) <= win.width()
    for w in (win.layers_panel, win.canvas, win.right_scroll):
        assert w.geometry().right() <= sp.width()
    # Seitenleisten: senkrecht scrollbar, Inhalt nicht abgeschnitten.
    for area in (win.right_scroll, win.layers_panel.scroll):
        assert isinstance(area, QScrollArea) and area.widgetResizable()
        assert _not_clipped(area)
    # Die rechte Leiste ist kompakt (compact_sidebar) und passt in ihre
    # Obergrenze: kein Seitwärts-Scrollen bei typischen Surface-/Laptop-Größen
    # (auch unter Windows-Schrift/DPI – Windows-CI läuft dieselben Tests).
    r = win.right_scroll
    need, cap = fit.sidebar_needed_width(r), fit.sidebar_cap(win.width())
    info = (f"need={need} cap={cap} vp={r.viewport().width()} "
            f"content={r.widget().minimumSizeHint().width()} sizes={sp.sizes()} {_widest(r)}")
    assert need <= cap, info
    assert not r.horizontalScrollBar().isVisible(), info
    assert r.width() >= need - 2, info
    la = win.layers_panel.scroll
    lneed, lcap = fit.sidebar_needed_width(la), fit.sidebar_cap(win.width(), fit.LAYERS_MAX_FRACTION)
    if lneed <= lcap:
        assert not la.horizontalScrollBar().isVisible(), f"need={lneed} cap={lcap} {_widest(la)}"
    # Canvas (inkl. Eigenschaftsleiste) passt, die Leiste scrollt notfalls.
    assert win.canvas.minimumSizeHint().width() <= win.canvas.width()
    assert _not_clipped(win.canvas.property_scroll)
    assert win.canvas.view.width() >= 200


@pytest.mark.parametrize("width", [1024, 1280])
def test_sidebar_fits_with_wide_windows_fonts(make_win, qapp, width):
    """Windows-CI (offscreen) misst Text ~1,9× breiter als Linux. Mit gleich
    breiter Schrift muss die rechte Leiste trotzdem ohne Seitwärts-Scrollen passen."""
    from PySide6.QtGui import QFont, QFontMetrics
    old = QFont(qapp.font())
    wide = QFont(old)
    # Ziel: Windows-CI-Breite dieses Texts (612 px); ist die Schrift schon so
    # breit (Windows), bleibt sie unverändert.
    adv = QFontMetrics(old).horizontalAdvance("Geladenes Mesh nach Kontrollmessung wiederverwenden")
    wide.setLetterSpacing(QFont.PercentageSpacing, max(100.0, min(200.0, 100.0 * 612 / max(1, adv))))
    qapp.setFont(wide)
    try:
        win = make_win(width, width * 9 // 16)
        r = win.right_scroll
        need, cap = fit.sidebar_needed_width(r), fit.sidebar_cap(width)
        info = f"need={need} cap={cap} sizes={win.splitter.sizes()} {_widest(r)}"
        assert need <= cap, info
        assert not r.horizontalScrollBar().isVisible(), info
    finally:
        qapp.setFont(old)


def test_compact_sidebar_wraps_rows_narrows_combos(qapp):
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                                   QPushButton, QVBoxLayout, QWidget)
    root = QWidget()
    lay = QVBoxLayout(root)
    form = QFormLayout()
    combo = QComboBox()
    combo.addItem("Ein sehr langer Materialname mit Dicke und Status (geprüft)")
    form.addRow("Material", combo)
    lay.addLayout(form)
    row = QHBoxLayout()
    btns = [QPushButton(t) for t in ("Vom Pi laden", "Auf Pi speichern", "Importieren …", "Exportieren …")]
    for b in btns:
        row.addWidget(b)
    row.addStretch(1)
    lay.addLayout(row)
    mixed = QHBoxLayout()  # Feld + Knöpfe: bleibt unverändert
    mixed.addWidget(QLabel("Schritt"))
    for t in ("Links", "Rechts", "Oben", "Unten"):
        mixed.addWidget(QPushButton(t))
    lay.addLayout(mixed)
    text = "Geladenes Mesh nach Kontrollmessung wiederverwenden (lang)"
    holder = QWidget()  # eigener Halter: Breite unabhängig von den Knöpfen
    QVBoxLayout(holder).addWidget(check := QCheckBox(text))
    lay.addWidget(holder)
    grid = QGridLayout()  # Panel-eigenes 2×2-Knopfraster mit breiten Knöpfen
    gbtns = [QPushButton(t * 3) for t in ("Home ", "Park ", "Fokus (G30) ", "Notstopp quittieren ")]
    for n, b in enumerate(gbtns):
        grid.addWidget(b, n // 2, n % 2)
    lay.addLayout(grid)
    status = QLabel("Nicht verbunden – Pi 400 antwortet nicht auf der Adresse")
    srow = QHBoxLayout()
    srow.addWidget(QPushButton("Verbinden"))
    srow.addWidget(status)
    lay.addLayout(srow)
    before = root.minimumSizeHint().width()
    combo_before = combo.minimumSizeHint().width()
    assert fit.compact_sidebar(root)
    assert not fit.compact_sidebar(root)  # idempotent
    assert form.rowWrapPolicy() == QFormLayout.WrapLongRows
    assert combo.minimumSizeHint().width() < combo_before
    assert combo.view().minimumWidth() >= combo.view().sizeHintForColumn(0)  # Popup bleibt lesbar
    assert all(b.parentWidget() is root for b in btns)
    root.show()
    qapp.processEvents()
    # 2×2 statt einer Reihe; bei breiter Schrift (Windows-CI) untereinander.
    assert len({b.y() for b in btns}) in (2, 4)
    assert mixed.count() == 5
    assert root.minimumSizeHint().width() < before
    # Langes Häkchen: schmal im Minimum, Text unverändert, bricht um.
    assert check.text() == text and check.toolTip() == text
    assert check.minimumWidth() == fit.COMPACT_CHECK_PX  # Layout-Minimum (qSmartMinSize)
    holder.setParent(None)
    holder.resize(fit.COMPACT_CHECK_PX + 30, 40)
    holder.show()
    settle(qapp)
    assert check.width() < check.sizeHint().width()
    assert check.height() > check.fontMetrics().lineSpacing() * 1.5
    check.click()
    assert check.isChecked()
    holder.grab()  # eigener Paint-Pfad läuft ohne Fehler
    holder.close()
    # Breites Knopfraster einspaltig in Lesereihenfolge, Statuszeile bricht um.
    assert [grid.getItemPosition(grid.indexOf(b))[:2] for b in gbtns] == [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert status.wordWrap()
    root.close()


def test_sidebar_refits_when_content_grows(make_win, qapp):
    """Wird der Inhalt später breiter (Schrift/DPI unter Windows, neue Felder),
    passt sich die Leiste an, statt waagerecht zu scrollen."""
    from PySide6.QtWidgets import QLabel
    win = make_win(1280, 720)
    content = win.right_scroll.widget()
    need0, cap = fit.sidebar_needed_width(win.right_scroll), fit.sidebar_cap(1280)
    if need0 + 40 > cap:
        pytest.skip(f"Inhalt schon breiter als die Obergrenze ({need0} > {cap - 40}): "
                    f"{_widest(win.right_scroll)}")
    wide = QLabel("breit")
    wide.setMinimumWidth(need0 + 20)
    content.layout().addWidget(wide)
    settle(qapp, 5)
    assert fit.sidebar_needed_width(win.right_scroll) <= fit.sidebar_cap(1280)
    assert not win.right_scroll.horizontalScrollBar().isVisible()
    assert win.right_scroll.viewport().width() >= wide.minimumWidth()


def test_very_narrow_window_scrolls_instead_of_clipping(make_win):
    win = make_win(800, 560)
    assert win.width() == 800
    assert win.minimumSizeHint().width() <= 800 or win.minimumWidth() <= 800
    for area in (win.right_scroll, win.layers_panel.scroll, win.canvas.property_scroll):
        assert _not_clipped(area)


@pytest.mark.parametrize("touch_on", [False, True])
def test_tool_strip_buttons_at_least_44px(make_win, touch_on):
    win = make_win(1280, 720)
    win.canvas.set_touch_mode(touch_on, persist=False)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    buttons = [b for b in win.canvas.tool_strip.findChildren(QToolButton) if b.defaultAction()]
    assert len(buttons) >= 7
    for b in buttons:
        assert b.width() >= 44 and b.height() >= 44, (b.defaultAction().text(), b.size())
    ys = sorted(b.y() for b in buttons)
    assert min(b - a for a, b in zip(ys, ys[1:])) >= 44 + 4  # Abstand zwischen Knöpfen


def test_small_screen_defaults_to_touch_mode(make_win, monkeypatch):
    monkeypatch.setattr(fit, "is_small_screen", lambda screen=None: True)
    win = make_win(1024, 600)
    assert win.canvas.touch_mode and win.layers_panel.touch_mode
    win.canvas.set_touch_mode(False)  # manuelle Wahl gewinnt
    assert not win.layers_panel.touch_mode


def test_large_screen_keeps_mouse_mode(make_win, monkeypatch):
    monkeypatch.setattr(fit, "is_small_screen", lambda screen=None: False)
    monkeypatch.setattr(touch, "has_touchscreen", lambda: False)
    win = make_win(1280, 720)
    assert not win.canvas.touch_mode


class _FakeScreen:
    def __init__(self, w, h):
        self._g = QRect(0, 0, w, h)

    def availableGeometry(self):  # noqa: N802
        return self._g


@pytest.mark.parametrize("avail", [(1368, 872), (1280, 680), (1024, 560), (2560, 1400)])
def test_default_window_size_fits_available_screen(avail):
    s = fit.default_window_size(_FakeScreen(*avail))
    assert s.width() <= avail[0] - 16 and s.height() <= avail[1] - 48
    assert s.width() <= 1400 and s.height() <= 900
    assert fit.is_small_screen(_FakeScreen(*avail)) == (avail[0] < 1500)
