"""Pfad menu / Datei menu: „Maske auf Bild anwenden“ and „Bildmaske lösen“ (LightBurn
*Tools › Apply Mask to Image* / *Remove Mask*).

Select one image and one or more closed shapes on top of it and run „Maske auf Bild anwenden“
(Ctrl+Alt+Shift+M, also in the canvas context menu's „Pfad“ sub-menu – long press in touch
mode): the shapes become the image's live mask in one undo step – outside the image turns
transparent and is not lasered, the original pixels stay. „Bildmaske lösen“ gives the outline
back as an editable closed shape and the image is whole again (one undo step). Computation in
:mod:`imagemask`; the destructive variant is :mod:`imagecrop_ui`.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

from . import imagemask
from .commands import AddShapesCommand, DeleteShapesCommand
from .edit_commands import ReplaceShapeCommand

APPLY = "image_mask"
RELEASE = "image_mask_release"
APPLY_TEXT = "Maske auf Bild anwenden"
RELEASE_TEXT = "Bildmaske lösen"
SHORTCUT = "Ctrl+Alt+Shift+M"
APPLY_TIP = ("Die ausgewählten geschlossenen Formen als Maske auf das Bild legen (wie LightBurns "
             "„Apply Mask to Image“): außerhalb wird das Bild durchsichtig und nicht gelasert, "
             "die Bildpunkte bleiben aber erhalten. Die Maske wandert mit dem Bild. Mehrere "
             "Formen / Löcher gelten wie eine Füllung (Kreis im Rechteck = Ring). Mit "
             "„Bildmaske lösen“ kommt die Form zurück.  (Strg+Alt+Umschalt+M)")
RELEASE_TIP = ("Die Maske vom Bild lösen (wie LightBurns „Remove Mask“): das Bild ist wieder "
               "ganz, die Maskenform kommt als bearbeitbare Form zurück – ändern oder "
               "verschieben und neu anwenden.")
MENU_ACTIONS = [APPLY, RELEASE]


class ImageMask:
    def __init__(self, editor) -> None:
        self.editor = editor

    def _shapes(self):
        ed = self.editor
        doc = ed.document
        return [doc.shape(i) for i in ed.selection if doc.has_shape(i)]

    def apply(self) -> bool:
        """Mask the one selected image with the selected shapes; True when changed."""
        ed = self.editor
        doc = ed.document
        shapes = self._shapes()
        images = [s for s in shapes if s.kind == "image" and s.image is not None]
        masks = imagemask.mask_shapes(s for s in shapes if s.kind != "image")
        if len(images) != 1:
            ed.notify("Bildmaske: genau ein Bild und darüber eine geschlossene Form (Rechteck, "
                      "Ellipse, Stern, Text …) auswählen.")
            return False
        image = images[0]
        if not doc.is_editable(image.id):
            ed.notify("Bildmaske: die Ebene des Bildes ist gesperrt.")
            return False
        if any(not doc.is_editable(m.id) for m in masks):
            ed.notify("Bildmaske: die Maskenform liegt auf einer gesperrten Ebene.")
            return False
        try:
            res = imagemask.apply_mask(image, masks)
        except imagemask.MaskError as e:
            ed.notify(f"Bildmaske: {e}")
            return False
        ed.undo_stack.beginMacro("Maske auf Bild anwenden")
        ed.undo_stack.push(ReplaceShapeCommand(doc, res.shape, "Maske auf Bild anwenden"))
        ed.undo_stack.push(DeleteShapesCommand(doc, [m.id for m in masks]))
        ed.undo_stack.endMacro()
        ed.set_selection([image.id])
        ed.notify(f"Maske angewandt: {round(res.kept_share * 100)} % des Bildes bleiben sichtbar "
                  f"– die Bildpunkte bleiben erhalten („Bildmaske lösen“ gibt die Form zurück)")
        return True

    def release(self) -> bool:
        """Release the mask of the selected images; True when changed."""
        ed = self.editor
        doc = ed.document
        images = [s for s in self._shapes() if s.kind == "image" and s.image is not None
                  and s.image.mask]
        if not images:
            ed.notify("Bildmaske lösen: ein Bild mit Maske auswählen.")
            return False
        if any(not doc.is_editable(s.id) for s in images):
            ed.notify("Bildmaske lösen: die Ebene des Bildes ist gesperrt.")
            return False
        ed.undo_stack.beginMacro("Bildmaske lösen")
        outlines = []
        for image in images:
            lid = image.image.mask_layer
            if not any(layer.id == lid for layer in doc.layers):
                lid = image.layer_id
            whole, outline = imagemask.release_mask(image, lid)
            ed.undo_stack.push(ReplaceShapeCommand(doc, whole, "Bildmaske lösen"))
            outlines.append(outline)
        ed.undo_stack.push(AddShapesCommand(doc, outlines, "Bildmaske lösen"))
        ed.undo_stack.endMacro()
        ed.set_selection([s.id for s in images] + [o.id for o in outlines])
        ed.notify("Bildmaske gelöst: das Bild ist wieder ganz, die Maskenform ist ausgewählt "
                  "(ändern und mit Strg+Alt+Umschalt+M neu anwenden)")
        return True


def install(editor) -> ImageMask:
    tool = ImageMask(editor)
    a = editor._act(APPLY, APPLY_TEXT, lambda _=False: tool.apply(), QKeySequence(SHORTCUT))
    a.setToolTip(APPLY_TIP)
    a.setStatusTip(APPLY_TIP)
    r = editor._act(RELEASE, RELEASE_TEXT, lambda _=False: tool.release(), None)
    r.setToolTip(RELEASE_TIP)
    r.setStatusTip(RELEASE_TIP)
    return tool
