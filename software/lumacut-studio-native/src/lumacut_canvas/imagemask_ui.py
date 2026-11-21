"""Pfad menu / Datei menu: „Maske auf Bild anwenden“ and „Bildmaske lösen“ (LightBurn
*Tools › Apply Mask to Image* / *Remove Mask*).

Select one image and one or more closed shapes on top of it and run „Maske auf Bild anwenden“
(Ctrl+Alt+Shift+M, also in the canvas context menu's „Pfad“ sub-menu – long press in touch
mode): the shapes become the image's live mask in one undo step – outside the image turns
transparent and is not lasered, the original pixels stay. „Bildmaske lösen“ gives the outline
back as an editable closed shape and the image is whole again (one undo step). Computation in
:mod:`imagemask`; the destructive variant is :mod:`imagecrop_ui`.

Several masks (round 104): applying shapes to an image that already has a mask narrows it to
the overlap; „Bereich im Bild ausblenden“ (Ctrl+Alt+Shift+H) is the inverse mask – the
shapes' area turns transparent, the rest stays (on a masked image: more holes). With several
images selected, every image the shapes overlap takes them in the same single undo step;
images the shapes do not touch stay as they are.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

from . import imagemask
from .commands import AddShapesCommand, DeleteShapesCommand
from .edit_commands import ReplaceShapeCommand

APPLY = "image_mask"
RELEASE = "image_mask_release"
HIDE = "image_mask_hide"
APPLY_TEXT = "Maske auf Bild anwenden"
RELEASE_TEXT = "Bildmaske lösen"
HIDE_TEXT = "Bereich im Bild ausblenden"
SHORTCUT = "Ctrl+Alt+Shift+M"
HIDE_SHORTCUT = "Ctrl+Alt+Shift+H"
APPLY_TIP = ("Die ausgewählten geschlossenen Formen als Maske auf das Bild legen (wie LightBurns "
             "„Apply Mask to Image“): außerhalb wird das Bild durchsichtig und nicht gelasert, "
             "die Bildpunkte bleiben aber erhalten. Die Maske wandert mit dem Bild. Mehrere "
             "Formen / Löcher gelten wie eine Füllung (Kreis im Rechteck = Ring). Mit "
             "„Bildmaske lösen“ kommt die Form zurück. Hat das Bild schon eine Maske, bleibt "
             "nur die Überschneidung sichtbar (Maske verkleinern). Mehrere ausgewählte Bilder "
             "bekommen die Form gemeinsam.  (Strg+Alt+Umschalt+M)")
HIDE_TIP = ("Umgekehrte Maske: die Fläche der ausgewählten geschlossenen Formen im Bild "
            "durchsichtig machen und nicht lasern, der Rest bleibt (z. B. Logo, Datumsstempel "
            "oder Hintergrundecke aus einem Foto nehmen). Auf einem Bild mit Maske kommen "
            "weitere Löcher dazu. Die Bildpunkte bleiben erhalten, „Bildmaske lösen“ gibt die "
            "Form zurück.  (Strg+Alt+Umschalt+H)")
RELEASE_TIP = ("Die Maske vom Bild lösen (wie LightBurns „Remove Mask“): das Bild ist wieder "
               "ganz, die Maskenform kommt als bearbeitbare Form zurück – ändern oder "
               "verschieben und neu anwenden.")
MENU_ACTIONS = [APPLY, HIDE, RELEASE]


class ImageMask:
    def __init__(self, editor) -> None:
        self.editor = editor

    def _shapes(self):
        ed = self.editor
        doc = ed.document
        return [doc.shape(i) for i in ed.selection if doc.has_shape(i)]

    def apply(self, mode: str = "keep") -> bool:
        """Mask the selected images with the selected shapes (``mode`` keep / hide, see
        :func:`imagemask.apply_mask`); True when changed."""
        ed = self.editor
        doc = ed.document
        shapes = self._shapes()
        images = [s for s in shapes if s.kind == "image" and s.image is not None]
        masks = imagemask.mask_shapes(s for s in shapes if s.kind != "image")
        title = "Bereich ausblenden" if mode == "hide" else "Bildmaske"
        if not images:
            ed.notify(f"{title}: ein Bild und darüber eine geschlossene Form (Rechteck, "
                      "Ellipse, Stern, Text …) auswählen.")
            return False
        if any(not doc.is_editable(im.id) for im in images):
            ed.notify(f"{title}: die Ebene des Bildes ist gesperrt.")
            return False
        if any(not doc.is_editable(m.id) for m in masks):
            ed.notify(f"{title}: die Maskenform liegt auf einer gesperrten Ebene.")
            return False
        results, errors = [], []
        for image in images:
            try:
                results.append(imagemask.apply_mask(image, masks, mode))
            except imagemask.MaskError as e:
                errors.append(str(e))
        if not results:
            ed.notify(f"{title}: {errors[0]}")
            return False
        label = HIDE_TEXT if mode == "hide" else APPLY_TEXT
        ed.undo_stack.beginMacro(label)
        for res in results:
            ed.undo_stack.push(ReplaceShapeCommand(doc, res.shape, label))
        ed.undo_stack.push(DeleteShapesCommand(doc, [m.id for m in masks]))
        ed.undo_stack.endMacro()
        ed.set_selection([res.shape.id for res in results])
        skipped = (f" – {len(errors)} Bild{'er' if len(errors) > 1 else ''} nicht berührt "
                   "und unverändert" if errors else "")
        if len(results) == 1:
            verb = "Bereich ausgeblendet" if mode == "hide" else "Maske angewandt"
            ed.notify(f"{verb}: {round(results[0].kept_share * 100)} % des Bildes bleiben "
                      f"sichtbar – die Bildpunkte bleiben erhalten („Bildmaske lösen“ gibt die "
                      f"Form zurück){skipped}")
        else:
            verb = "ausgeblendet" if mode == "hide" else "maskiert"
            ed.notify(f"{len(results)} Bilder {verb} – die Bildpunkte bleiben erhalten "
                      f"(„Bildmaske lösen“ gibt die Formen zurück){skipped}")
        return True

    def hide(self) -> bool:
        """Make the selected shapes' area of the selected images transparent (inverse mask)."""
        return self.apply("hide")

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
    hd = editor._act(HIDE, HIDE_TEXT, lambda _=False: tool.hide(), QKeySequence(HIDE_SHORTCUT))
    hd.setToolTip(HIDE_TIP)
    hd.setStatusTip(HIDE_TIP)
    r = editor._act(RELEASE, RELEASE_TEXT, lambda _=False: tool.release(), None)
    r.setToolTip(RELEASE_TIP)
    r.setStatusTip(RELEASE_TIP)
    return tool
