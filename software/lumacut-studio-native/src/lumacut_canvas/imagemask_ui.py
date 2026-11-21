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

Soft edge (round 105): „Weiche Maskenkante …“ (Ctrl+Alt+Shift+F) asks for a width in mm and
lets the masked image fade to white (= no burn) inside its mask edge – a vignette like an oval
portrait on wood. Preview in the dialog, quick buttons, 0 mm = hard edge again; all selected
masked images in one undo step. Computation in :func:`imagemask.set_feather`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QPushButton)

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
FEATHER = "image_mask_feather"
FEATHER_TEXT = "Weiche Maskenkante …"
FEATHER_SHORTCUT = "Ctrl+Alt+Shift+F"
FEATHER_TIP = ("Die Maskenkante eines Bildes weich machen: innen an der Kante blendet das Bild "
               "über die eingestellte Breite sanft auf Weiß aus (= nicht lasern) – z. B. ein "
               "ovales Porträt mit weichem Rand (Vignette) auf Holz. Außerhalb der Maske bleibt "
               "alles frei, die Bildpunkte bleiben erhalten; 0 mm macht die Kante wieder hart. "
               "Am besten mit Dithering (Jarvis, Floyd) oder Graustufen.  (Strg+Alt+Umschalt+F)")
FEATHER_DEFAULT_MM = 3.0
FEATHER_PRESETS_MM = (0.0, 2.0, 5.0, 10.0)
MENU_ACTIONS = [APPLY, HIDE, RELEASE, FEATHER]


class FeatherDialog(QDialog):
    """Width of the soft mask edge (mm) with a small preview of the first image."""

    def __init__(self, image, parent=None, value_mm: float = FEATHER_DEFAULT_MM,
                 touch: bool = False, count: int = 1) -> None:
        super().__init__(parent)
        self.setWindowTitle("Weiche Maskenkante")
        self.image = image
        form = QFormLayout(self)
        self.preview = QLabel()
        self.preview.setObjectName("FeatherPreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(220, 120)
        self.preview.setToolTip("Vorschau wie gelasert: Weiß = kein Laser")
        form.addRow(self.preview)
        self.width = QDoubleSpinBox()
        self.width.setObjectName("FeatherWidth")
        self.width.setRange(*imagemask.FEATHER_RANGE_MM)
        self.width.setDecimals(1)
        self.width.setSingleStep(0.5)
        self.width.setSuffix(" mm")
        self.width.setValue(float(value_mm))
        self.width.setToolTip("Breite des Verlaufs innen an der Maskenkante (0 = harte Kante)")
        if touch:
            self.width.setMinimumHeight(44)
        form.addRow("Breite", self.width)
        row = QHBoxLayout()
        self.preset_buttons = []
        for mm in FEATHER_PRESETS_MM:
            b = QPushButton("hart" if mm == 0 else f"{mm:g} mm")
            b.setObjectName(f"FeatherPreset_{mm:g}")
            if touch:
                b.setMinimumHeight(44)
            b.clicked.connect(lambda _=False, v=mm: self.width.setValue(v))
            row.addWidget(b)
            self.preset_buttons.append(b)
        form.addRow(row)
        self.readout = QLabel()
        self.readout.setObjectName("FeatherReadout")
        self.readout.setWordWrap(True)
        form.addRow(self.readout)
        self.count = count
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if touch:
            for b in self.buttons.buttons():
                b.setMinimumHeight(44)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.width.valueChanged.connect(self.update_preview)
        self.update_preview()

    def value(self) -> float:
        return float(self.width.value())

    def update_preview(self) -> None:
        mm = self.value()
        arr = imagemask.feather_preview(self.image, mm)
        h, w = arr.shape
        img = QImage(arr.tobytes(), w, h, w, QImage.Format_Grayscale8).copy()
        self.preview.setPixmap(QPixmap.fromImage(img))
        px = mm * imagemask.px_per_mm(self.image)
        many = f" – gilt für alle {self.count} ausgewählten Bilder mit Maske" if self.count > 1 else ""
        if px <= 0.5:
            text = "Harte Kante: das Bild endet scharf an der Maske."
        else:
            text = (f"Verlauf {mm:g} mm (≈ {px:.0f} Bildpunkte) innen an der Maskenkante: das "
                    f"Bild blendet weich auf Weiß aus, außerhalb wird nicht gelasert. Mit "
                    f"Dithering wird der Rand immer lichter.")
        self.readout.setText(text + many)


class ImageMask:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.last_feather_mm = FEATHER_DEFAULT_MM   # last soft edge width (session)
        self.ask_feather = None                     # tests: callable(image, mm, count) -> mm | None

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

    def _ask_feather(self, image, value_mm: float, count: int):
        dlg = FeatherDialog(image, self.editor, value_mm,
                            touch=bool(getattr(self.editor, "touch_mode", False)), count=count)
        return dlg.value() if dlg.exec() == QDialog.Accepted else None

    def feather(self) -> bool:
        """Ask for the soft edge width and set it on the selected masked images."""
        ed = self.editor
        doc = ed.document
        images = [s for s in self._shapes() if s.kind == "image" and s.image is not None]
        masked = [s for s in images if s.image.mask]
        if not masked:
            ed.notify("Weiche Maskenkante: ein Bild mit Maske auswählen" +
                      (" – erst „Maske auf Bild anwenden“ oder „Bereich im Bild ausblenden“."
                       if images else "."))
            return False
        if any(not doc.is_editable(s.id) for s in masked):
            ed.notify("Weiche Maskenkante: die Ebene des Bildes ist gesperrt.")
            return False
        current = imagemask.feather_mm(masked[0])
        ask = getattr(self, "ask_feather", None) or self._ask_feather
        mm = ask(masked[0], round(current, 1) if current > 0 else self.last_feather_mm,
                 len(masked))
        if mm is None:
            return False
        results, errors = [], []
        for image in masked:
            try:
                results.append(imagemask.set_feather(image, mm))
            except imagemask.MaskError as e:
                errors.append(str(e))
        if not results:
            ed.notify(f"Weiche Maskenkante: {errors[0]}")
            return False
        if mm > 0:
            self.last_feather_mm = float(mm)
        ed.undo_stack.beginMacro("Weiche Maskenkante")
        for res in results:
            ed.undo_stack.push(ReplaceShapeCommand(doc, res.shape, "Weiche Maskenkante"))
        ed.undo_stack.endMacro()
        ed.set_selection([res.shape.id for res in results])
        skipped = (f" – {len(images) - len(results)} Bild"
                   f"{'er' if len(images) - len(results) > 1 else ''} ohne Maske oder unverändert"
                   if len(images) > len(results) else "")
        what = "1 Bild" if len(results) == 1 else f"{len(results)} Bilder"
        if results[0].feather_px <= 0:
            ed.notify(f"Maskenkante wieder hart ({what}){skipped}")
        else:
            share = round(results[0].soft_share * 100)
            ed.notify(f"Weiche Maskenkante {mm:g} mm ({what}): das Bild blendet innen an der "
                      f"Kante auf Weiß aus ({share} % der sichtbaren Fläche im Verlauf) – 0 mm "
                      f"macht die Kante wieder hart{skipped}")
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
    hd = editor._act(HIDE, HIDE_TEXT, lambda _=False: tool.hide(), QKeySequence(HIDE_SHORTCUT))
    hd.setToolTip(HIDE_TIP)
    hd.setStatusTip(HIDE_TIP)
    r = editor._act(RELEASE, RELEASE_TEXT, lambda _=False: tool.release(), None)
    r.setToolTip(RELEASE_TIP)
    r.setStatusTip(RELEASE_TIP)
    f = editor._act(FEATHER, FEATHER_TEXT, lambda _=False: tool.feather(),
                    QKeySequence(FEATHER_SHORTCUT))
    f.setToolTip(FEATHER_TIP)
    f.setStatusTip(FEATHER_TIP)
    return tool
