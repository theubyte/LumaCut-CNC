"""Drawing tone curves for the material test dialog (review round 54).

LightBurn / xTool test an image with the settings the user has drawn; until
round 53 the material-test dialog only offered the curve presets (and the
curves of a reopened spec). :class:`CurveDrawDialog` reuses the image
dialog's :class:`lumacut_import.curve_widget.CurveWidget` over the histogram
of the grid's test image, starts from a preset, from the curve of an image in
the document or from the chosen curve, and hands back normalised points
``((in, out), ...)`` (``()`` = linear). :func:`document_image_curves` lists
the non-linear curves of the document's images (selected images first) so a
curve drawn in the image settings can be tested as it is.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QVBoxLayout)

from lumacut_canvas.model import normalize_curve

from .material_test import MaterialTestSpec, cell_image_png

DOC_CURVE_PREFIX = "Bild"


def document_image_curves(document, selection: Iterable[str] = ()) -> list[tuple[str, tuple]]:
    """``(label, curve)`` of every image in ``document`` with a non-linear tone
    curve, selected images first, each curve once. Labels: „Bild <Ebene> N“ –
    numbered in document order so they stay stable when the selection changes."""
    if document is None:
        return []
    shapes = [s for s in getattr(document, "shapes", ())
              if getattr(s, "kind", "") == "image" and getattr(s, "image", None) is not None]
    labels: dict[str, str] = {}
    for n, s in enumerate(shapes, 1):
        labels[s.id] = f"{DOC_CURVE_PREFIX} {n}"
    chosen = set(selection or ())
    ordered = [s for s in shapes if s.id in chosen] + [s for s in shapes if s.id not in chosen]
    out: list[tuple[str, tuple]] = []
    seen: set = set()
    for s in ordered:
        curve = normalize_curve(s.image.settings.curve)
        if not curve or curve in seen:
            continue
        seen.add(curve)
        out.append((labels[s.id], curve))
    return out


def grid_image_histogram(spec: MaterialTestSpec | None) -> np.ndarray | None:
    """Histogram (256 bins) of the grid's shared test image at the curve's input
    (black / white point of the spec applied); None when it cannot be read."""
    if spec is None:
        return None
    try:
        png, _, _ = cell_image_png(spec)
        from lumacut_import.image_preview import curve_input_histogram, gray_from_png
        gray = gray_from_png(png)
    except Exception:  # noqa: BLE001 - background only
        return None
    hist = np.bincount(gray.ravel(), minlength=256)[:256].astype(float)
    o = spec.image_options or {}
    black, white = int(o.get("black_point", 0)), int(o.get("white_point", 255))
    if 0 <= black < white <= 255:
        hist = curve_input_histogram(hist, black, white)
    return hist


class CurveDrawDialog(QDialog):
    """Draw one tone curve: template combo (presets, document images) + editor."""

    def __init__(self, curve=(), parent=None, templates: Iterable[tuple[str, tuple]] = (),
                 histogram=None, title: str = "Gradationskurve zeichnen") -> None:
        super().__init__(parent)
        from lumacut_import.curve_widget import CURVE_PRESETS, CUSTOM_LABEL, CurveWidget
        self.setWindowTitle(title)
        self.setObjectName("material_test_curve_dialog")
        self._templates: list[tuple[str, tuple]] = [
            (name, normalize_curve(pts)) for name, pts in CURVE_PRESETS.items()]
        known = {c for _, c in self._templates}
        for label, c in templates or ():
            c = normalize_curve(c)
            if c not in known:
                known.add(c)
                self._templates.append((label, c))
        self._custom_label = CUSTOM_LABEL
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.template = QComboBox()
        self.template.setObjectName("material_test_curve_template")
        for label, _ in self._templates:
            self.template.addItem(label)
        self.template.addItem(CUSTOM_LABEL)
        self.template.setToolTip("Ausgangskurve: Vorlage oder die Kurve eines Bildes im "
                                 "Dokument – danach unten frei bearbeiten.")
        form.addRow("Vorlage", self.template)
        lay.addLayout(form)
        self.editor = CurveWidget(curve)
        self.editor.setObjectName("material_test_curve_editor")
        self.editor.setMinimumSize(240, 220)
        if histogram is not None:
            self.editor.set_histogram(histogram)
        lay.addWidget(self.editor)
        hint = QLabel("Punkt ziehen; neben die Kurve tippen = neuer Punkt; Doppel-/Rechtsklick "
                      "= löschen. Hintergrund: Histogramm des Testbilds.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)
        self._sync_template(self.editor.curve())
        self.template.activated.connect(self._template_chosen)
        self.editor.curve_changed.connect(self._sync_template)

    def curve(self) -> tuple:
        """Normalised points of the drawn curve (``()`` = linear)."""
        return self.editor.curve()

    def set_curve(self, curve) -> None:
        self.editor.set_curve(curve, emit=True)

    def template_names(self) -> list[str]:
        return [label for label, _ in self._templates]

    def _sync_template(self, curve) -> None:
        c = normalize_curve(curve)
        idx = next((i for i, (_, t) in enumerate(self._templates) if t == c),
                   len(self._templates))
        self.template.blockSignals(True)
        self.template.setCurrentIndex(idx)
        self.template.blockSignals(False)

    def _template_chosen(self, index: int) -> None:
        if 0 <= index < len(self._templates):
            self.editor.set_curve(self._templates[index][1], emit=True)
        self._sync_template(self.editor.curve())
