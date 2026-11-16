"""Pfad menu / Datei menu: „Bild mit Form zuschneiden“ (LightBurn *Tools › Crop Image*,
xTool „Zuschneiden“ with a shape).

Select one image and one or more closed shapes on top of it (rectangle, ellipse, star,
text, closed path) and run the action (Ctrl+Alt+M, also in the canvas context menu's
„Pfad“ sub-menu – long press in touch mode). The image is replaced by its cropped copy
(same id) in one undo step; the shapes stay so they can be cut out around the photo
(delete them with Entf when only the engraving is wanted). Computation in :mod:`imagecrop`.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

from . import imagecrop
from .edit_commands import ReplaceShapeCommand

ACTION = "image_crop"
TEXT = "Bild mit Form zuschneiden"
SHORTCUT = "Ctrl+Alt+M"
TIP = ("Bild auf die ausgewählten geschlossenen Formen zuschneiden (wie LightBurns „Crop Image“ / "
       "xTool „Zuschneiden“): außerhalb wird das Bild durchsichtig und nicht gelasert, das Bild "
       "schrumpft auf den Rest. Mehrere Formen / Löcher gelten wie eine Füllung (Kreis im "
       "Rechteck = Ring). Die Formen bleiben zum Ausschneiden erhalten.  (Strg+Alt+M)")
MENU_ACTIONS = [ACTION]


class ImageCrop:
    def __init__(self, editor) -> None:
        self.editor = editor

    def _selection(self):
        ed = self.editor
        doc = ed.document
        shapes = [doc.shape(i) for i in ed.selection if doc.has_shape(i)]
        images = [s for s in shapes if s.kind == "image" and s.image is not None]
        masks = imagecrop.mask_shapes(s for s in shapes if s.kind != "image")
        return images, masks

    def crop(self) -> bool:
        """Crop the one selected image to the selected shapes; True when changed."""
        ed = self.editor
        images, masks = self._selection()
        if len(images) != 1:
            ed.notify("Bild zuschneiden: genau ein Bild und darüber eine geschlossene Form "
                      "(Rechteck, Ellipse, Stern, Text …) auswählen.")
            return False
        image = images[0]
        if not ed.document.is_editable(image.id):
            ed.notify("Bild zuschneiden: die Ebene des Bildes ist gesperrt.")
            return False
        try:
            res = imagecrop.crop_image(image, masks)
        except imagecrop.CropError as e:
            ed.notify(f"Bild zuschneiden: {e}")
            return False
        ed.undo_stack.push(ReplaceShapeCommand(ed.document, res.shape, "Bild zuschneiden"))
        ed.set_selection([image.id])
        w, h = res.px
        ed.notify(f"Bild zugeschnitten: {w} × {h} Pixel, {round(res.kept_share * 100)} % des "
                  f"Bildes bleiben – die Form bleibt zum Ausschneiden erhalten (Entf löscht sie)")
        return True


def install(editor) -> ImageCrop:
    tool = ImageCrop(editor)
    a = editor._act(ACTION, TEXT, lambda _=False: tool.crop(), QKeySequence(SHORTCUT))
    a.setToolTip(TIP)
    a.setStatusTip(TIP)
    return tool
