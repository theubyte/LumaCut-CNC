import QtQuick
import QtQuick.Layouts
import LumaCut

// Below the layers: what is selected and everything that can be set about it.
ColumnLayout {
    id: root
    objectName: "props-panel"
    spacing: Theme.sp3
    readonly property var s: Editor.sel
    readonly property int count: s.count || 0

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        Layout.topMargin: Theme.sp3
        LcText { text: "Eigenschaften"; font.weight: Font.DemiBold; Layout.fillWidth: true }
        LcText { visible: root.count > 0; text: root.count > 1 ? root.count + " Objekte" : (root.s.kind || ""); kind: "smallFaint" }
    }

    // Nothing selected
    ColumnLayout {
        visible: root.count === 0
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        Layout.bottomMargin: Theme.sp3
        spacing: Theme.sp2
        LcText {
            Layout.fillWidth: true
            text: "Nichts ausgewählt. Klick wählt ein Objekt, Rahmen aufziehen wählt mehrere, Rechtsklick öffnet das Menü."
            kind: "smallFaint"
            wrapMode: Text.WordWrap
            lineHeight: 1.2
        }
        GridLayout {
            visible: (Editor.stats.count || 0) > 0
            Layout.fillWidth: true
            columns: 2
            columnSpacing: Theme.sp3
            rowSpacing: 2
            LcText { text: "Objekte auf der Platte"; kind: "smallMuted"; Layout.fillWidth: true }
            LcText { objectName: "stats-count"; Layout.alignment: Qt.AlignRight; text: Editor.stats.count || 0; kind: "small"; tnum: true }
            LcText { visible: Editor.stats.w !== undefined; text: "Ausmaß"; kind: "smallMuted" }
            LcText { visible: Editor.stats.w !== undefined; Layout.alignment: Qt.AlignRight; text: Fmt.trim(Editor.stats.w || 0, 1) + " × " + Fmt.trim(Editor.stats.h || 0, 1) + " mm"; kind: "small"; tnum: true }
        }
    }

    // Geometry
    GridLayout {
        visible: root.count > 0 && root.s.hasBox === true
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        columns: 3
        columnSpacing: 2
        rowSpacing: Theme.sp2
        LcField {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            label: "X"
            LcNumber { objectName: "prop-x"; value: root.s.x || 0; unit: "mm"; digits: 2; onEdited: (v) => Editor.setPosX(v) }
        }
        Item { Layout.preferredWidth: Theme.hControlSm; Layout.preferredHeight: 1 }
        LcField {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            label: "Y"
            LcNumber { objectName: "prop-y"; value: root.s.y || 0; unit: "mm"; digits: 2; onEdited: (v) => Editor.setPosY(v) }
        }
        LcField {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            label: "Breite"
            LcNumber { objectName: "prop-w"; value: root.s.w || 0; unit: "mm"; digits: 2; min: 0.01; onEdited: (v) => Editor.setSizeW(v) }
        }
        LcButton {
            objectName: "lock-aspect"
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: 3
            variant: "ghost"; size: "sm"
            icon: Editor.lockAspect ? "link-2" : "link-2-off"
            pressedLook: Editor.lockAspect
            tip: Editor.lockAspect ? "Seitenverhältnis gesperrt. Klick: frei" : "Seitenverhältnis frei. Klick: sperren"
            onClicked: Editor.lockAspect = !Editor.lockAspect
        }
        LcField {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            label: "Höhe"
            LcNumber { objectName: "prop-h"; value: root.s.h || 0; unit: "mm"; digits: 2; min: 0.01; onEdited: (v) => Editor.setSizeH(v) }
        }
        LcField {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            label: "Drehung"
            LcNumber { objectName: "prop-rot"; value: root.s.rot || 0; unit: "°"; digits: 1; onEdited: (v) => Editor.setRotation(v) }
        }
        Item { Layout.preferredWidth: Theme.hControlSm; Layout.preferredHeight: 1 }
        RowLayout {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignBottom
            spacing: Theme.sp1
            LcButton { objectName: "prop-rot90"; Layout.fillWidth: true; size: "sm"; implicitHeight: Theme.hControl; icon: "rotate-cw"; text: "90°"; tip: "Um 90° drehen"; onClicked: Editor.rotateBy90() }
            LcButton { objectName: "prop-center"; Layout.fillWidth: true; size: "sm"; implicitHeight: Theme.hControl; text: "Mitte"; tip: "In die Mitte der Arbeitsfläche"; onClicked: Editor.centerInWork() }
        }
    }

    // Text
    Rectangle { visible: root.s.isText === true; Layout.fillWidth: true; Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3; Layout.preferredHeight: 1; color: Theme.line }
    ColumnLayout {
        visible: root.s.isText === true
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        spacing: Theme.sp2
        LcField {
            Layout.fillWidth: true
            label: "Text"
            Rectangle {
                implicitHeight: Math.max(52, textInput.contentHeight + 14)
                radius: Theme.rMd
                color: Theme.surface
                border.width: 1
                border.color: textInput.activeFocus ? Theme.accent : Theme.line2
                Rectangle { anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3; border.color: Theme.accentSoft; visible: textInput.activeFocus }
                TextEdit {
                    id: textInput
                    objectName: "text-input"
                    anchors.fill: parent
                    anchors.margins: 7
                    color: Theme.text
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.accentInk
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    renderType: TextEdit.NativeRendering
                    font.family: Theme.font
                    font.pixelSize: Theme.fsMd
                    onTextChanged: if (activeFocus) Editor.typeText(text)
                    onActiveFocusChanged: { if (!activeFocus) { Editor.endTextEdit(); text = Editor.sel.text || "" } }
                    Keys.onEscapePressed: root.forceActiveFocus()
                }
                Connections {
                    target: Editor
                    function onSelChanged() { if (!textInput.activeFocus) textInput.text = Editor.sel.text || "" }
                    function onFocusTextRequested() { Qt.callLater(root.focusText) }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.sp2
            LcField {
                Layout.fillWidth: true
                label: "Schrift"
                LcButton {
                    objectName: "font-select"
                    text: root.s.fontLabel || ""
                    onClicked: Editor.dialog = "font"
                }
            }
            LcField {
                Layout.preferredWidth: 92
                label: "Größe"
                LcNumber { objectName: "font-size"; value: root.s.fontSize || 10; unit: "mm"; step: 1; min: 0.5; max: 300; onEdited: (v) => Editor.setFontSize(v) }
            }
        }
        LcCheck { objectName: "font-bold"; text: "Fett"; checked: root.s.bold === true; onToggled: (on) => Editor.setBold(on) }
    }

    // Picture
    Rectangle { visible: root.s.isImage === true; Layout.fillWidth: true; Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3; Layout.preferredHeight: 1; color: Theme.line }
    ColumnLayout {
        visible: root.s.isImage === true
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        spacing: Theme.sp2
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: width * (root.s.pxH || 1) / Math.max(root.s.pxW || 1, 1)
            Layout.maximumHeight: 112
            color: Theme.sheet
            radius: Theme.rSm
            border.width: 1
            border.color: Theme.line
            clip: true
            ComputeImage {
                id: preview
                objectName: "image-preview"
                anchors.fill: parent
                anchors.margins: 1
                mode: root.s.imageMode === "threshold" ? 1 : root.s.imageMode === "grayscale" ? 0 : 2
                brightness: root.s.brightness || 0
                contrast: root.s.contrast || 0
                invert: root.s.invert === true
            }
        }
        LcField {
            Layout.fillWidth: true
            label: "Bildmodus"
            LcButton {
                id: modeBtn
                objectName: "image-mode"
                text: ({ grayscale: "Graustufen", dither: "Dithering Floyd-Steinberg", jarvis: "Dithering Jarvis", stucki: "Dithering Stucki", threshold: "Schwellwert (nur Schwarz und Weiß)" })[root.s.imageMode] || ""
                onClicked: modeMenu.openAt(modeBtn)
            }
        }
        LcMenu {
            id: modeMenu
            objectName: "image-mode-list"
            items: [
                { label: "Graustufen", action: () => Editor.setImageMode("grayscale") },
                { label: "Dithering Floyd-Steinberg", action: () => Editor.setImageMode("dither") },
                { label: "Dithering Jarvis", action: () => Editor.setImageMode("jarvis") },
                { label: "Dithering Stucki", action: () => Editor.setImageMode("stucki") },
                { label: "Schwellwert (nur Schwarz und Weiß)", action: () => Editor.setImageMode("threshold") }
            ]
        }
        LcField {
            Layout.fillWidth: true
            label: "Helligkeit"
            LcSlider { objectName: "image-brightness"; value: root.s.brightness || 0; min: -100; max: 100; onMoved: (v) => Editor.adjustImage("brightness", v); onCommitted: Editor.adjustDone() }
        }
        LcField {
            Layout.fillWidth: true
            label: "Kontrast"
            LcSlider { objectName: "image-contrast"; value: root.s.contrast || 0; min: -100; max: 100; onMoved: (v) => Editor.adjustImage("contrast", v); onCommitted: Editor.adjustDone() }
        }
        LcField {
            Layout.fillWidth: true
            label: "Schärfe"
            LcSlider { objectName: "image-sharpen"; value: root.s.sharpen || 0; min: 0; max: 100; onMoved: (v) => Editor.adjustImage("sharpen", v); onCommitted: Editor.adjustDone() }
        }
        LcCheck { objectName: "image-invert"; text: "Umkehren (Negativ)"; checked: root.s.invert === true; onToggled: (on) => Editor.setImageInvert(on) }
        LcText {
            Layout.fillWidth: true
            text: (root.s.pxW || 0) + " × " + (root.s.pxH || 0) + " Pixel, " + (root.s.dpi || 0) + " dpi. Die Fläche zeigt, wie das Bild gelasert würde."
            kind: "smallFaint"
            wrapMode: Text.WordWrap
        }
        LcButton { objectName: "vectorize"; Layout.alignment: Qt.AlignLeft; text: "Vektorisieren …"; onClicked: Editor.dialog = "vectorize" }
    }

    // Warnings
    Rectangle { visible: (root.s.warnText || "").length > 0; Layout.fillWidth: true; Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3; Layout.preferredHeight: 1; color: Theme.line }
    ColumnLayout {
        objectName: "props-warning"
        visible: (root.s.warnText || "").length > 0
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        spacing: Theme.sp2
        LcNote { objectName: "props-warning-note"; Layout.fillWidth: true; tone: root.s.warnTone || "warn"; text: root.s.warnText || "" }
        LcButton { objectName: "keep-inside"; size: "sm"; Layout.alignment: Qt.AlignLeft; text: root.s.warnAction || ""; onClicked: Editor.keepInside() }
    }
    Item { Layout.preferredHeight: Theme.sp2 }

    function focusText() {
        textInput.text = Editor.sel.text || ""
        textInput.forceActiveFocus()
        textInput.selectAll()
    }
    property string imageKey: s.isImage === true ? (s.imageKey || "") : ""
    onImageKeyChanged: if (imageKey.length) Qt.callLater(root.showImage)
    function showImage() { if (imageKey.length) Editor.showImageIn(preview) }
}
