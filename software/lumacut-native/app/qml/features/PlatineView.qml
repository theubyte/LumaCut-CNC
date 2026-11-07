import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import LumaCut

// Platine: fabrication files left, the board as it lies under the laser in the middle, settings, laser values and the
// workshop steps right. All logic is in the Platine singleton; the diode removes lacquer, the board is etched afterwards.
Item {
    id: root
    objectName: "view-Platine"

    // Test handle: everything a native file dialog cannot reach.
    Item {
        objectName: "platine-api"
        function loadExample(_) { Platine.loadExample(); return true }
        function loadFiles(paths) { Platine.loadPaths(paths); return true }
        function info(_) { return Platine.info() }
        function busy(_) { return Platine.busy }
        function set(a) { Platine.set(a[0], a[1]); return Platine.settings }
        function setStage(s) { Platine.setStage(s); return Platine.stage }
        function setKind(a) { Platine.setKind(a[0], a[1]); return true }
        function checks(_) { return Platine.checks }
        function jobLayers(_) { return Platine.jobLayers }
        function viewLayers(_) { return Platine.viewLayers }
        function toProject(_) { Platine.toProject(); return true }
        function clear(_) { Platine.clear(); return true }
        function shown(_) { return preview.shownElements }
        function fit(_) { preview.fitView(); return true }
    }

    Connections {
        target: Platine
        function onFilesRequested() { picker.nameFilters = Platine.fileFilters(); picker.open() }
    }
    FileDialog {
        id: picker
        title: "Gerber- und Bohrdateien wählen"
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            const list = []
            for (const u of selectedFiles) list.push(u.toString())
            Platine.loadPaths(list)
        }
    }

    // Nothing loaded yet: one clear invitation.
    Item {
        anchors.fill: parent
        visible: Platine.files.length === 0
        Rectangle { anchors.fill: parent; color: Theme.bg }
        LcCard {
            objectName: "pcb-empty"
            anchors.centerIn: parent
            width: Math.min(parent.width - 2 * Theme.sp6, 560)
            padding: Theme.sp6
            spacing: Theme.sp3
            LcIcon { name: "circuit-board"; size: 34; width: 34; height: 34; color: Theme.faint; Layout.alignment: Qt.AlignHCenter }
            LcText { text: "Gerber-Daten laden"; kind: "h2"; Layout.alignment: Qt.AlignHCenter }
            LcText {
                text: "Gerber RS-274X und Excellon, einzeln oder als ZIP, zum Beispiel aus KiCad oder EasyEDA. Der Laser entfernt Lack, nicht Kupfer: geätzt wird danach von Hand."
                kind: "muted"; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Theme.sp2
                spacing: Theme.sp2
                LcButton { objectName: "pcb-pick"; variant: "primary"; icon: "file-up"; text: "Dateien wählen"; onClicked: Platine.askFiles() }
                LcButton { objectName: "pcb-example"; icon: "wand-2"; text: "Beispielplatine laden"; onClicked: Platine.loadExample() }
            }
            RowLayout {
                visible: Platine.busy
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.sp2
                LcSpinner {}
                LcText { text: Platine.busyText; kind: "smallMuted" }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        visible: Platine.files.length > 0
        PlFiles {
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.panel
        }
        Rectangle {
            objectName: "pcb-canvas"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            color: Theme.canvas
            clip: true
            PlatineStage {
                id: preview
                objectName: "pcb-preview"
                anchors.fill: parent
                anchors.margins: Theme.sp4
                canvasColor: "transparent"
                sheetColor: Theme.sheet
                edgeColor: Theme.line2
                boardColor: Theme.pcbBoard
                copperColor: Theme.pcbCopper
                laserColor: Theme.pcbLaser
                drillColor: Theme.pcbDrill
                markColor: Theme.pcbMark
                maskColor: Theme.pcbMask
                silkColor: Theme.pcbSilk
                badColor: Theme.bad
                function fitView() { fit() }
            }
            // What the picture shows, and how it relates to the machine.
            Row {
                x: Theme.sp4 + Theme.sp2
                y: Theme.sp4 + Theme.sp2
                spacing: Theme.sp2
                LcChip {
                    objectName: "pcb-view-chip"
                    text: (Platine.settings.side === "bottom" ? "Unterseite" : "Oberseite") + (Platine.settings.mirror ? ", gespiegelt" : "") + ", so liegt sie unter dem Laser"
                    icon: "eye"
                }
                LcChip { visible: Platine.jobSize.length > 0; text: "Auftrag " + Platine.jobSize }
            }
            LcButton {
                objectName: "pcb-fit"
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.sp4 + Theme.sp2
                size: "sm"
                icon: "maximize"
                tip: "Ganze Platine zeigen"
                onClicked: preview.fit()
            }
            Rectangle {
                objectName: "pcb-busy"
                visible: Platine.busy
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Theme.sp5
                width: busyRow.implicitWidth + 2 * Theme.sp3
                height: Theme.hControl
                radius: Theme.rMd
                color: Theme.surface
                border.width: 1
                border.color: Theme.line
                Row {
                    id: busyRow
                    anchors.centerIn: parent
                    spacing: Theme.sp2
                    LcSpinner { anchors.verticalCenter: parent.verticalCenter }
                    LcText { text: Platine.busyText; kind: "smallMuted"; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }
        PlSide {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.max(Theme.panel + Theme.sp6, Math.min(root.width * 0.3, Theme.panelWide))
        }
    }
}
