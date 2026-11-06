import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import LumaCut

// Dialogs of the editor. Native file dialogs are a thin shell around Editor.importPaths and Editor.exportTo.
Item {
    id: root
    property var files

    Connections {
        target: Editor
        function onImportRequested(onlyImages) {
            importPick.nameFilters = onlyImages ? ["Bilder (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"] : Editor.importFilters()
            importPick.open()
        }
        function onExportRequested(format) {
            exportPick.format = format
            exportPick.nameFilters = [format.toUpperCase() + " (*." + format + ")"]
            exportPick.currentFile = "file:///" + Editor.exportFileName(format)
            exportPick.open()
        }
    }
    FileDialog {
        id: importPick
        title: "Importieren"
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            const list = []
            for (const u of selectedFiles) list.push(u.toString())
            Editor.importPaths(list)
        }
    }
    FileDialog {
        id: exportPick
        property string format: "svg"
        title: "Exportieren"
        fileMode: FileDialog.SaveFile
        onAccepted: Editor.exportTo(selectedFile.toString(), format)
    }

    LcDialog {
        id: contour
        objectName: "contour-dialog"
        open: Editor.dialog === "contour"
        title: "Kontur erzeugen"
        dialogWidth: 420
        property real offset: 2
        property bool outer: true
        property bool remove: false
        onRejected: Editor.dialog = ""
        LcText { Layout.fillWidth: true; kind: "muted"; wrapMode: Text.WordWrap; text: "Zieht eine Linie im festen Abstand um die Auswahl. Sie kommt auf die Ebene Schneiden." }
        LcField {
            label: "Abstand"
            Layout.preferredWidth: 120
            LcNumber { objectName: "contour-offset"; value: contour.offset; unit: "mm"; step: 0.5; min: -50; max: 100; onEdited: (v) => contour.offset = v }
        }
        LcCheck { objectName: "contour-outer"; text: "Nur der äußere Rand, Löcher ignorieren"; checked: contour.outer; onToggled: (on) => contour.outer = on }
        LcCheck { objectName: "contour-remove"; text: "Ausgangsform entfernen"; checked: contour.remove; onToggled: (on) => contour.remove = on }
        footer: [
            LcButton { text: "Abbrechen"; onClicked: Editor.dialog = "" },
            LcButton { objectName: "contour-ok"; variant: "primary"; text: "Kontur erzeugen"; busy: Editor.busy; onClicked: Editor.makeContour(contour.offset, contour.remove, contour.outer) }
        ]
    }

    LcDialog {
        id: vector
        objectName: "vectorize-dialog"
        open: Editor.dialog === "vectorize"
        title: "Bild vektorisieren"
        dialogWidth: 440
        property int threshold: 128
        property bool invert: false
        property bool smooth: true
        property bool outerOnly: false
        property bool remove: false
        onRejected: Editor.dialog = ""
        LcText { Layout.fillWidth: true; kind: "muted"; wrapMode: Text.WordWrap; text: "Macht aus dunklen Bildteilen Pfade, die sich schneiden oder markieren lassen." }
        LcField {
            label: "Schwellwert"
            Layout.fillWidth: true
            LcSlider { objectName: "vectorize-threshold"; value: vector.threshold; min: 1; max: 254; onMoved: (v) => vector.threshold = v }
        }
        LcCheck { text: "Helle statt dunkle Teile"; checked: vector.invert; onToggled: (on) => vector.invert = on }
        LcCheck { text: "Kanten glätten"; checked: vector.smooth; onToggled: (on) => vector.smooth = on }
        LcCheck { text: "Nur äußere Umrisse"; checked: vector.outerOnly; onToggled: (on) => vector.outerOnly = on }
        LcCheck { text: "Bild danach entfernen"; checked: vector.remove; onToggled: (on) => vector.remove = on }
        footer: [
            LcButton { text: "Abbrechen"; onClicked: Editor.dialog = "" },
            LcButton { objectName: "vectorize-ok"; variant: "primary"; text: "Vektorisieren"; busy: Editor.busy; onClicked: Editor.vectorizeSel(vector.threshold, vector.invert, vector.smooth, vector.outerOnly, vector.remove) }
        ]
    }

    LcDialog {
        id: rename
        objectName: "rename-dialog"
        open: Editor.dialog === "rename"
        title: "Projekt umbenennen"
        dialogWidth: 420
        initialFocus: nameField.input
        onOpenChanged: if (open) { nameField.text = Document.title; nameField.selectAll() }
        onRejected: Editor.dialog = ""
        function ok() {
            const t = nameField.text.trim()
            if (t.length) Document.title = t
            Editor.dialog = ""
        }
        LcInput { id: nameField; objectName: "rename-input"; Layout.fillWidth: true; onAccepted: rename.ok() }
        footer: [
            LcButton { text: "Abbrechen"; onClicked: Editor.dialog = "" },
            LcButton { objectName: "rename-ok"; variant: "primary"; text: "Umbenennen"; onClicked: rename.ok() }
        ]
    }

    LcDialog {
        id: exportDlg
        objectName: "export-dialog"
        open: Editor.dialog === "export"
        title: "Exportieren"
        dialogWidth: 440
        property string format: "svg"
        readonly property var info: open ? Editor.exportInfo(format) : ({})
        onRejected: Editor.dialog = ""
        LcField {
            label: "Format"
            LcSegmented {
                objectName: "export-format"
                implicitWidth: 200
                value: exportDlg.format
                options: [{ value: "svg", label: "SVG", tip: "Vektoren für andere Programme" }, { value: "dxf", label: "DXF", tip: "Für CAD" }, { value: "png", label: "PNG", tip: "Bild der Platte" }]
                onActivated: (v) => exportDlg.format = v
            }
        }
        LcText { objectName: "export-info"; kind: "muted"; text: exportDlg.info.text || "" }
        Repeater {
            model: exportDlg.info.warnings || []
            LcNote { required property string modelData; Layout.fillWidth: true; tone: "warn"; text: modelData }
        }
        footer: [
            LcButton { text: "Abbrechen"; onClicked: Editor.dialog = "" },
            LcButton { objectName: "export-ok"; variant: "primary"; text: "Exportieren"; enabled: exportDlg.info.empty === false; busy: Editor.busy; onClicked: Editor.askExport(exportDlg.format) }
        ]
    }

    LcDialog {
        id: fontDlg
        objectName: "font-dialog"
        open: Editor.dialog === "font"
        title: "Schrift wählen"
        dialogWidth: 420
        initialFocus: fontSearch.input
        property string query: ""
        readonly property var all: open ? Editor.fontFamilies() : []
        readonly property var shown: { const q = query.toLowerCase(); return all.filter((f) => Editor.fontLabel(f).toLowerCase().includes(q)) }
        onRejected: Editor.dialog = ""
        LcInput { id: fontSearch; objectName: "font-search"; Layout.fillWidth: true; icon: "search"; placeholder: "Suchen"; onEdited: (t) => fontDlg.query = t }
        ListView {
            id: fontList
            Layout.fillWidth: true
            Layout.preferredHeight: 320
            clip: true
            model: fontDlg.shown
            boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                id: fontRow
                required property string modelData
                required property int index
                objectName: "font-" + index
                width: fontList.width
                height: Theme.hControl
                radius: Theme.rSm
                color: fontArea.containsMouse ? Theme.surface3 : "transparent"
                LcText { anchors.left: parent.left; anchors.leftMargin: Theme.sp2; anchors.verticalCenter: parent.verticalCenter; text: Editor.fontLabel(fontRow.modelData) }
                MouseArea {
                    id: fontArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { Editor.setFontFamily(fontRow.modelData); Editor.dialog = "" }
                }
            }
        }
        footer: [ LcButton { text: "Abbrechen"; onClicked: Editor.dialog = "" } ]
    }
}
