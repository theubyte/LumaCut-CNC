import QtQuick
import QtQuick.Layouts
import LumaCut

// File menu, undo, then what fits the selection; on the right background, snapping and zoom.
Rectangle {
    id: root
    objectName: "mv-toolbar"
    required property var stage
    color: Theme.surface
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    readonly property bool narrow: width < 1080
    readonly property var sel: Editor.sel
    readonly property bool any: (sel.count || 0) > 0
    readonly property string hintWhere: (sel.units || 0) > 1 ? "" : " an der Arbeitsfläche"

    component Sep: Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; Layout.leftMargin: Theme.sp1; Layout.rightMargin: Theme.sp1; color: Theme.line }
    component Tool: LcButton { variant: "ghost" }

    readonly property var fileItems: [
        { label: "Neu", kbd: "Strg+N", action: () => files.run("new") },
        { separator: true },
        { label: "Öffnen vom Pi …", kbd: "Strg+O", action: () => files.run("open") },
        { label: "Datei öffnen …", action: () => files.run("openLocal") },
        { separator: true },
        { label: "Speichern auf dem Pi", kbd: "Strg+S", action: () => files.run("save") },
        { label: "Als Datei speichern …", kbd: "Strg+Umschalt+S", action: () => files.run("saveLocal") },
        { label: "Umbenennen …", action: () => files.run("rename") },
        { separator: true },
        { label: "Importieren …", kbd: "Strg+I", action: () => files.run("import") },
        { label: "Exportieren …", kbd: "Strg+E", action: () => files.run("export") }
    ]
    readonly property var alignItems: [
        { label: "Links", icon: "align-start-vertical", action: () => Editor.align("left") },
        { label: "Mitte waagerecht", icon: "align-center-vertical", action: () => Editor.align("centerX") },
        { label: "Rechts", icon: "align-end-vertical", action: () => Editor.align("right") },
        { separator: true },
        { label: "Oben", icon: "align-start-horizontal", action: () => Editor.align("top") },
        { label: "Mitte senkrecht", icon: "align-center-horizontal", action: () => Editor.align("centerY") },
        { label: "Unten", icon: "align-end-horizontal", action: () => Editor.align("bottom") },
        { separator: true },
        { label: "Waagerecht verteilen", icon: "align-horizontal-distribute-center", disabled: (sel.units || 0) < 3, action: () => Editor.distribute(true) },
        { label: "Senkrecht verteilen", icon: "align-vertical-distribute-center", disabled: (sel.units || 0) < 3, action: () => Editor.distribute(false) }
    ]

    MvFiles { id: files }
    LcMenu { id: fileMenu; objectName: "file-menu-list"; items: root.fileItems }
    LcMenu { id: alignMenu; objectName: "align-menu-list"; items: root.alignItems }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.sp2
        anchors.rightMargin: Theme.sp2
        anchors.bottomMargin: 1
        spacing: 2
        LcButton {
            id: fileBtn
            objectName: "file-menu"
            variant: "ghost"
            text: "Datei"
            onClicked: fileMenu.openAt(fileBtn)
            implicitWidth: 76
            LcIcon { anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter; name: "chevron-down"; size: 13; width: 13; height: 13; color: Theme.muted }
            textColor: Theme.text
        }
        Sep {}
        Tool { objectName: "undo"; icon: "undo-2"; tip: "Rückgängig (Strg+Z)"; enabled: Document.canUndo; onClicked: Document.undo() }
        Tool { objectName: "redo"; icon: "redo-2"; tip: "Wiederholen (Strg+Y)"; enabled: Document.canRedo; onClicked: Document.redo() }

        Sep { visible: root.any }
        Tool {
            id: alignBtn
            objectName: "align-menu"
            visible: root.any && root.narrow
            icon: "align-center-vertical"
            tip: "Ausrichten und verteilen"
            onClicked: alignMenu.openAt(alignBtn)
        }
        Tool { objectName: "align-left"; visible: root.any && !root.narrow; icon: "align-start-vertical"; tip: "Links ausrichten" + root.hintWhere; onClicked: Editor.align("left") }
        Tool { objectName: "align-centerX"; visible: root.any && !root.narrow; icon: "align-center-vertical"; tip: "Waagerecht mittig" + root.hintWhere; onClicked: Editor.align("centerX") }
        Tool { objectName: "align-right"; visible: root.any && !root.narrow; icon: "align-end-vertical"; tip: "Rechts ausrichten" + root.hintWhere; onClicked: Editor.align("right") }
        Tool { objectName: "align-top"; visible: root.any && !root.narrow; icon: "align-start-horizontal"; tip: "Oben ausrichten" + root.hintWhere; onClicked: Editor.align("top") }
        Tool { objectName: "align-centerY"; visible: root.any && !root.narrow; icon: "align-center-horizontal"; tip: "Senkrecht mittig" + root.hintWhere; onClicked: Editor.align("centerY") }
        Tool { objectName: "align-bottom"; visible: root.any && !root.narrow; icon: "align-end-horizontal"; tip: "Unten ausrichten" + root.hintWhere; onClicked: Editor.align("bottom") }
        Tool { objectName: "dist-h"; visible: root.any && !root.narrow && (root.sel.units || 0) >= 3; icon: "align-horizontal-distribute-center"; tip: "Waagerecht verteilen"; onClicked: Editor.distribute(true) }
        Tool { objectName: "dist-v"; visible: root.any && !root.narrow && (root.sel.units || 0) >= 3; icon: "align-vertical-distribute-center"; tip: "Senkrecht verteilen"; onClicked: Editor.distribute(false) }
        Sep { visible: root.any }
        Tool { objectName: "mirror-h"; visible: root.any; icon: "flip-horizontal-2"; tip: "Links und rechts spiegeln"; onClicked: Editor.mirror(true) }
        Tool { objectName: "mirror-v"; visible: root.any; icon: "flip-vertical-2"; tip: "Oben und unten spiegeln"; onClicked: Editor.mirror(false) }
        Sep { visible: (root.sel.vectors || 0) >= 2 }
        Tool { objectName: "bool-union"; visible: (root.sel.vectors || 0) >= 2; icon: "squares-unite"; tip: "Verschweißen"; onClicked: Editor.booleanSel("union") }
        Tool { objectName: "bool-subtract"; visible: (root.sel.vectors || 0) >= 2; icon: "squares-subtract"; tip: "Abziehen: vordere von der untersten Form"; onClicked: Editor.booleanSel("subtract") }
        Tool { objectName: "bool-intersect"; visible: (root.sel.vectors || 0) >= 2; icon: "squares-intersect"; tip: "Schnittmenge"; onClicked: Editor.booleanSel("intersect") }
        Sep { visible: root.any }
        Tool { objectName: "group"; visible: (root.sel.count || 0) >= 2; icon: "group"; tip: "Gruppieren (Strg+G)"; onClicked: Editor.group() }
        Tool { objectName: "ungroup"; visible: root.sel.anyGroup === true; icon: "ungroup"; tip: "Gruppe auflösen (Strg+Umschalt+G)"; onClicked: Editor.ungroup() }
        Tool { objectName: "split"; visible: root.sel.canSplit === true; icon: "split"; tip: "In einzelne Teile aufteilen"; onClicked: Editor.splitSel() }
        Tool { objectName: "contour"; visible: root.any; icon: "square-dashed"; tip: "Kontur erzeugen"; onClicked: Editor.dialog = "contour" }

        Item { Layout.fillWidth: true }

        Tool {
            id: camBtn
            objectName: "bg-button"
            icon: "camera"
            tip: "Kamerabild als Hintergrund"
            pressedLook: Editor.bgOn && Editor.bgLoaded
            onClicked: bgPop.openAt(camBtn)
        }
        Sep {}
        Tool { objectName: "snap-grid"; icon: "grid-3x3"; tip: "Am Raster einrasten: " + (Editor.snapGrid ? "an" : "aus"); pressedLook: Editor.snapGrid; onClicked: Editor.snapGrid = !Editor.snapGrid }
        Tool { objectName: "snap-objects"; icon: "magnet"; tip: "An Objekten einrasten: " + (Editor.snapObjects ? "an" : "aus") + " (Strg beim Ziehen setzt aus)"; pressedLook: Editor.snapObjects; onClicked: Editor.snapObjects = !Editor.snapObjects }
        Sep {}
        Tool { objectName: "zoom-out"; icon: "zoom-out"; tip: "Verkleinern (Strg+-)"; onClicked: root.stage.zoomCentered(0.8) }
        LcButton {
            objectName: "zoom-label"
            variant: "ghost"
            text: root.stage.zoomPercent + " %"
            textColor: Theme.muted
            implicitWidth: 56
            tip: "Maßstab: 100 % ist echte Größe am Bildschirm. Klick: Arbeitsfläche einpassen."
            onClicked: root.stage.fitBed()
        }
        Tool { objectName: "zoom-in"; icon: "zoom-in"; tip: "Vergrößern (Strg++)"; onClicked: root.stage.zoomCentered(1.25) }
        Tool { objectName: "fit"; icon: "maximize"; tip: "Einpassen (F), Auswahl einpassen (Umschalt+F)"; onClicked: root.stage.fitBed() }
    }

    MvPopover {
        id: bgPop
        objectName: "bg-pop"
        popWidth: 270
        ColumnLayout {
            width: parent.width
            spacing: Theme.sp2
            LcText { text: "Kamerabild als Hintergrund"; font.weight: Font.DemiBold }
            LcButton {
                objectName: "bg-load"
                size: "sm"
                Layout.alignment: Qt.AlignLeft
                busy: Editor.bgBusy
                text: Editor.bgBusy ? "Lädt …" : Editor.bgLoaded ? "Neu vom Pi laden" : "Scan vom Pi laden"
                onClicked: Editor.loadBackground()
            }
            LcCheck { objectName: "bg-show"; visible: Editor.bgLoaded; text: "Anzeigen"; checked: Editor.bgOn; onToggled: (on) => Editor.bgOn = on }
            LcField {
                visible: Editor.bgLoaded
                Layout.fillWidth: true
                label: "Deckkraft"
                LcSlider { objectName: "bg-alpha"; min: 10; max: 100; unit: "%"; value: Math.round(Editor.bgAlpha * 100); onMoved: (v) => Editor.bgAlpha = v / 100 }
            }
            LcNote { Layout.fillWidth: true; text: "Nur zur Orientierung, wird nie gelasert. Das Werkstück kann verschoben sein: vor dem Lasern neu scannen." }
        }
    }
}
