"""Edit generated objects again (Qt side of :mod:`lumacut_job.generated`).

Double click on a QR code, barcode, Data Matrix or arc text (select tool) or
„Code bearbeiten…“ (Alt+E) opens the generator's dialog with the stored
parameters – sizes scaled by what the user did with the handles – and replaces
the group in one undo step: same layer, same centre, same rotation, same
enclosing groups and the same group id, so a later double click works again.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from lumacut_canvas.commands import AddShapesCommand, DeleteShapesCommand
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import generated
from .generated import Unit

EDIT_TITLES = {"qr": "QR-Code bearbeiten", "barcode": "Barcode bearbeiten",
               "datamatrix": "Data Matrix bearbeiten", "arctext": "Bogentext bearbeiten"}


def build_shapes(spec, layer_id: str) -> list:
    """Fresh, unrotated, tagged shapes for ``spec`` (centred in the work area)."""
    kind = generated.spec_kind(spec)
    s = spec.normalized()
    if kind == "qr":
        from . import qr
        from .qr_qt import centered
        code = qr.encode(s.text, s.ec)
        shapes = qr.qr_shapes(centered(s, None, code), layer_id, code)
    elif kind == "datamatrix":
        from . import datamatrix as dm
        from .datamatrix_qt import centered
        code = s.encode()
        shapes = dm.datamatrix_shapes(centered(s, None, code), layer_id, code)
    elif kind == "barcode":
        from . import barcode
        from .barcode_qt import glyph_fn
        code = s.encode()
        shapes = barcode.barcode_shapes(barcode.centered(s, None, code), layer_id, code,
                                        glyph_fn(s.font_family))
    else:
        from . import arctext
        from .arctext_qt import glyphs_for
        if not s.text.strip():
            raise ValueError("Bitte Text eingeben")
        glyphs = glyphs_for(s.text, s.font_family, s.height_mm, s.bold, s.italic)
        shapes = arctext.arc_shapes(glyphs, s, layer_id, (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0),
                                    cap_height_mm=s.height_mm)
    if not shapes:
        raise ValueError("Nichts zu erzeugen")
    return generated.tag(shapes, s)


def unit_spec(unit: Unit):
    """Stored parameters, scaled to the size the group has now."""
    return generated.scaled_spec(generated.spec_from_meta(unit.meta), unit.scale)


def replace_unit(editor, unit: Unit, spec) -> list[str]:
    """Replace the generated group by a new one from ``spec`` (one undo step).

    The new group keeps layer, centre, rotation, enclosing groups and group id.
    Raises ``ValueError`` (invalid parameters, locked layer, kind changed).
    """
    doc = editor.document
    if generated.spec_kind(spec) != unit.kind:
        raise ValueError("Objektart lässt sich nicht ändern")
    layer = doc.layer(unit.layer_id)
    if layer.locked:
        raise ValueError(f"Ebene „{layer.name}“ ist gesperrt")
    shapes = build_shapes(spec, unit.layer_id)
    generated.place(shapes, unit.center, unit.rot)
    for sh in shapes:
        sh.groups = unit.outer + (unit.group,)
    label = generated.LABELS[unit.kind]
    stack = editor.undo_stack
    stack.beginMacro(f"{label} bearbeiten")
    try:
        stack.push(DeleteShapesCommand(doc, list(unit.ids)))
        stack.push(AddShapesCommand(doc, shapes, label))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


def edit_dialog(unit: Unit, spec, layer, parent=None) -> QDialog:
    """The generator's own dialog in edit mode (no new-layer / replace option)."""
    from .qr_qt import layer_fills
    if unit.kind == "qr":
        from .qr_qt import QrDialog
        dlg = QrDialog(parent, spec, active_layer=layer)
    elif unit.kind == "datamatrix":
        from .datamatrix_qt import DataMatrixDialog
        dlg = DataMatrixDialog(parent, spec, active_layer=layer)
    elif unit.kind == "barcode":
        from .barcode_qt import BarcodeDialog
        dlg = BarcodeDialog(parent, spec, active_layer=layer)
    else:
        from .arctext_qt import ArcTextDialog
        dlg = ArcTextDialog(parent, spec, can_replace=False)
    dlg.setWindowTitle(EDIT_TITLES[unit.kind])
    dlg.ok_button.setText("Übernehmen")
    fill = getattr(dlg, "fill", None)
    if fill is not None:
        dlg._active_fills = layer_fills(layer)
        fill.setChecked(False)
        fill.setVisible(False)
        dlg._update()
    return dlg


def generated_unit(editor, shape_id: str | None = None) -> Unit | None:
    """Generated group for ``shape_id`` or the current selection.

    ``None``: nothing generated selected. ``ValueError``: selected, but no
    longer editable (or more than one generated object selected).
    """
    doc = editor.document
    if shape_id is not None:
        return generated.find_unit(doc, shape_id)
    sel = [i for i in (getattr(editor, "selection", ()) or ()) if doc.has_shape(i)]
    units: dict[str, Unit] = {}
    for i in sel:
        u = generated.find_unit(doc, i)
        if u is not None:
            units.setdefault(u.group, u)
    if len(units) > 1:
        raise ValueError("Bitte nur ein erzeugtes Objekt auswählen")
    return next(iter(units.values()), None)


__all__ = ["EDIT_TITLES", "build_shapes", "edit_dialog", "generated_unit", "replace_unit",
           "unit_spec"]
