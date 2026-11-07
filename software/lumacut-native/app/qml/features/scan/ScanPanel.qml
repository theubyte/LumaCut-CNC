import QtQuick
import QtQuick.Layouts
import LumaCut

// Camera in the motif: workplace scan, the scan as background, live picture. Logic in Scanner; moves only after a go.
ColumnLayout {
    id: root
    property var stage: null
    /** The popover around this panel: it closes before the go dialog asks. */
    property var popup: null
    spacing: Theme.sp2
    function viewBox() {
        if (!stage) return
        const a = stage.itemToMm(Qt.point(0, 0)), b = stage.itemToMm(Qt.point(stage.width, stage.height))
        Scanner.setViewBox(a.x, a.y, b.x, b.y)
    }

    LcText { text: "Kamera und Scan"; font.weight: Font.DemiBold }
    LcNote {
        objectName: "scan-uncalibrated"
        visible: !Scanner.calibrated
        Layout.fillWidth: true
        tone: "warn"
        text: Scanner.calibrationNote
    }
    LcButton {
        objectName: "scan-to-calibration"
        visible: !Scanner.calibrated
        size: "sm"
        icon: "crosshair"; text: "Zu Maschine, Kalibrieren"
        onClicked: { AppSettings.setValue("maschineTab", "kalibrieren"); Shell.navigate("maschine") }
    }

    LcText { text: "Arbeitsplatz scannen"; kind: "section"; Layout.topMargin: Theme.sp1 }
    LcSegmented {
        objectName: "scan-region"
        Layout.fillWidth: true
        options: [{ value: "all", label: "Ganze Fläche" }, { value: "motif", label: "Motiv" }, { value: "view", label: "Ausschnitt" }]
        value: Scanner.region
        onActivated: (v) => Scanner.region = v
    }
    LcText {
        Layout.fillWidth: true
        kind: "smallFaint"
        wrapMode: Text.WordWrap
        text: Scanner.region === "motif" ? "Unter dem Motiv der aktiven Platte, 10 mm Rand." : Scanner.region === "view" ? "Was die Bühne gerade zeigt. Ein Teil-Scan ersetzt nur diesen Bereich." : "Das ganze Bett, Bild für Bild."
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.sp2
        LcButton {
            objectName: "scan-start"
            visible: !Scanner.running
            variant: "primary"; size: "sm"
            icon: "scan-line"; text: "Scannen"
            lock: Scanner.lock([Machine.status, Scanner.calibrated, Scanner.running])
            onClicked: { root.viewBox(); if (root.popup) root.popup.open = false; Scanner.scan() }
        }
        LcButton {
            objectName: "scan-cancel"
            visible: Scanner.running
            size: "sm"
            icon: "x"; text: "Abbrechen"
            onClicked: Scanner.cancel()
        }
        LcText { visible: Scanner.running; objectName: "scan-step"; text: Scanner.stepText; kind: "smallMuted"; Layout.fillWidth: true; elide: Text.ElideRight }
    }
    LcProgress { visible: Scanner.running; Layout.fillWidth: true; value: Scanner.steps ? Scanner.step / Scanner.steps : 0 }
    LcText { objectName: "scan-result"; visible: !Scanner.running && Scanner.lastResult.length > 0; text: Scanner.lastResult; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    LcNote { Layout.fillWidth: true; tone: "warn"; text: "Objekt verschoben? Neu scannen. Vor jedem Abtasten und Lasern muss der Scan zum liegenden Objekt passen." }

    LcText { text: "Hintergrund"; kind: "section"; Layout.topMargin: Theme.sp1 }
    LcText { objectName: "bg-stamp"; visible: Editor.bgLoaded; text: "Stand: " + (Scanner.backgroundStamp || "geladen"); kind: "smallMuted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
    RowLayout {
        Layout.fillWidth: true
        LcCheck { objectName: "bg-show"; visible: Editor.bgLoaded; text: "Anzeigen"; checked: Editor.bgOn; onToggled: (on) => Editor.bgOn = on }
        Item { Layout.fillWidth: true }
        LcButton { objectName: "bg-load"; size: "sm"; variant: "ghost"; icon: "refresh-cw"; text: "Vom Pi laden"; onClicked: Scanner.reloadBackground() }
    }
    LcField {
        visible: Editor.bgLoaded
        Layout.fillWidth: true
        label: "Deckkraft"
        LcSlider { objectName: "bg-alpha"; min: 10; max: 100; unit: "%"; value: Math.round(Editor.bgAlpha * 100); onMoved: (v) => Editor.bgAlpha = v / 100 }
    }

    LcText { text: "Live-Bild"; kind: "section"; Layout.topMargin: Theme.sp1 }
    LcCheck { objectName: "live-window"; text: "Fenster mit dem Kamerabild"; checked: Scanner.liveOn; onToggled: (on) => Scanner.liveOn = on }
    LcCheck {
        objectName: "live-overlay"
        enabled: Scanner.calibrated
        text: "Entzerrt auf der Bühne, an der Kopfposition"
        checked: Scanner.liveOverlay
        onToggled: (on) => Scanner.liveOverlay = on
    }
    LcCheck { objectName: "live-light"; text: "Kamera-Licht für jedes Bild einschalten"; checked: Scanner.liveLight; onToggled: (on) => Scanner.liveLight = on }
    LcText { Layout.fillWidth: true; kind: "smallFaint"; wrapMode: Text.WordWrap; text: "Nur zur Orientierung, wird nie gelasert." }
}
