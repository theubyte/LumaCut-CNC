import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import LumaCut

// Below the preview, folded by default: what waits on the Pi and what is stored there.
Rectangle {
    id: root
    objectName: "start-dock"
    color: Theme.surface
    implicitHeight: head.height + (Start.dockOpen ? Theme.dockBody : 0)
    Rectangle { width: parent.width; height: 1; color: Theme.line; z: 2 }

    Rectangle {
        id: head
        objectName: "dock-toggle"
        width: parent.width
        height: Theme.hControlLg
        color: headArea.containsMouse ? Theme.surface2 : "transparent"
        Row {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp3
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.sp3
            Row {
                spacing: Theme.sp1
                LcText { text: "Warteschlange"; font.weight: Font.Medium }
                LcText { objectName: "queue-count"; text: Start.queueWaiting; font.weight: Font.DemiBold; tnum: true }
            }
            Row {
                spacing: Theme.sp1
                LcText { text: "Gespeicherte Aufträge"; font.weight: Font.Medium }
                LcText { objectName: "jobs-count"; text: Start.jobs.length; font.weight: Font.DemiBold; tnum: true }
            }
        }
        LcIcon {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp3
            anchors.verticalCenter: parent.verticalCenter
            name: Start.dockOpen ? "chevron-down" : "chevron-up"
            size: 15; width: 15; height: 15
            color: Theme.muted
        }
        MouseArea { id: headArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Start.dockOpen = !Start.dockOpen }
    }

    RowLayout {
        visible: Start.dockOpen
        anchors.top: head.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        spacing: 0
        // ---- Queue ----
        ColumnLayout {
            objectName: "start-queue"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            Layout.margins: Theme.sp3
            spacing: Theme.sp2
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { objectName: "queue-title"; text: Start.queueTitle; kind: "section"; Layout.fillWidth: true; elide: Text.ElideRight }
                LcButton { objectName: "queue-add-current"; visible: !Start.isSaved; icon: "list-plus"; text: "Motiv einreihen"; size: "sm"; tip: "Das aktuelle Motiv hochladen und hinten anstellen"; enabled: Start.segmentCount > 0 && !JobBuilder.building && !Start.busy.length; busy: Start.busy === "queue"; onClicked: Start.enqueueCurrent() }
                LcButton { objectName: "queue-pause"; visible: Start.queueActive; icon: "pause"; text: "Pause"; size: "sm"; enabled: !Start.queuePausing; onClicked: Start.queueOp("queue_pause") }
                LcButton { objectName: "queue-run"; visible: !Start.queueActive; icon: "play"; text: Start.queueRunLabel; size: "sm"; enabled: Start.queueCanRun; lock: Machine.free ? "" : (Machine.freeLock || "Die Maschine ist noch beschäftigt: einen Moment warten."); onClicked: Start.queueOp("queue_run") }
                LcButton { objectName: "queue-clear"; text: "Leeren"; size: "sm"; variant: "ghost"; enabled: Start.queueItems.length > 0; onClicked: Start.queueOp("queue_clear") }
            }
            LcText {
                visible: Start.queueItems.length === 0
                text: "Leer. Reihe das aktuelle Motiv oder einen gespeicherten Auftrag ein: alles läuft dann nacheinander, jeder Auftrag mit eigener Abtastung."
                kind: "muted"; wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Item { visible: Start.queueItems.length === 0; Layout.fillHeight: true }
            LcScroll {
                visible: Start.queueItems.length > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                padding: 0
                spacing: 2
                Repeater {
                    model: Start.queueItems
                    Rectangle {
                        required property var modelData
                        required property int index
                        objectName: "queue-item-" + index
                        Layout.fillWidth: true
                        implicitHeight: queueRow.implicitHeight + Theme.sp1 * 2
                        radius: Theme.rSm
                        color: "transparent"
                        RowLayout {
                            id: queueRow
                            anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: Theme.sp1; anchors.rightMargin: Theme.sp1
                            spacing: Theme.sp2
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                LcText { text: modelData.file; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                LcText { visible: modelData.error.length > 0; text: modelData.error; kind: "small"; color: Theme.bad; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            }
                            LcChip { objectName: "queue-state-" + index; text: modelData.label; tone: modelData.tone }
                            LcButton { objectName: "queue-skip-" + index; visible: modelData.canSkip; icon: "skip-forward"; size: "sm"; variant: "ghost"; tip: "Überspringen"; onClicked: Start.queueOp("queue_skip", modelData.id) }
                            LcButton { objectName: "queue-remove-" + index; visible: modelData.canRemove; icon: "x"; size: "sm"; variant: "ghost"; tip: "Entfernen"; onClicked: Start.queueOp("queue_remove", modelData.id) }
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: Theme.line }

        // ---- Saved jobs ----
        ColumnLayout {
            objectName: "start-jobs"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            Layout.margins: Theme.sp3
            spacing: Theme.sp2
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Gespeicherte Aufträge"; kind: "section"; Layout.fillWidth: true; elide: Text.ElideRight }
                LcButton { objectName: "job-upload"; icon: "upload"; text: "Hochladen"; size: "sm"; tip: "G-Code-Datei vom PC auf den Pi laden"; onClicked: uploadPick.open() }
            }
            LcText {
                visible: Start.jobs.length === 0
                text: "Noch keine Aufträge auf dem Pi. Jeder Start und jedes Einreihen legt einen an."
                kind: "muted"; wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Item { visible: Start.jobs.length === 0; Layout.fillHeight: true }
            LcScroll {
                visible: Start.jobs.length > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                padding: 0
                spacing: 2
                Repeater {
                    model: Start.jobs
                    Rectangle {
                        id: jobRow
                        required property var modelData
                        required property int index
                        objectName: "job-row-" + index
                        readonly property bool selected: Start.isSaved && Start.name === modelData.name
                        readonly property bool waiting: { for (const it of Start.queueItems) if (it.file === modelData.name && (it.state === "queued" || it.state === "running")) return true; return false }
                        readonly property bool runs: Start.running && Start.runFile === modelData.name
                        Layout.fillWidth: true
                        implicitHeight: jobCol.implicitHeight + Theme.sp1 * 2
                        radius: Theme.rSm
                        color: selected ? Theme.accentSoft : jobArea.containsMouse ? Theme.surface2 : "transparent"
                        MouseArea { id: jobArea; objectName: "job-open-" + index; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Start.previewSaved(jobRow.modelData.name) }
                        RowLayout {
                            anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: Theme.sp1; anchors.rightMargin: Theme.sp1
                            spacing: 2
                            ColumnLayout {
                                id: jobCol
                                Layout.fillWidth: true
                                spacing: 1
                                LcText { text: jobRow.modelData.name; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                LcText { text: jobRow.modelData.line; kind: "smallFaint"; font.pixelSize: Theme.fsXs; tnum: true; Layout.fillWidth: true; elide: Text.ElideRight }
                            }
                            LcButton { objectName: "job-preview-" + jobRow.index; icon: "eye"; size: "sm"; variant: "ghost"; tip: "Vorschau"; onClicked: Start.previewSaved(jobRow.modelData.name) }
                            LcButton { objectName: "job-enqueue-" + jobRow.index; icon: "list-plus"; size: "sm"; variant: "ghost"; tip: "In die Warteschlange"; onClicked: Start.enqueueSaved(jobRow.modelData.name) }
                            LcButton { objectName: "job-export-" + jobRow.index; icon: "download"; size: "sm"; variant: "ghost"; tip: "G-Code exportieren"; onClicked: { exportPick.jobName = jobRow.modelData.name; exportPick.currentFile = "file:///" + jobRow.modelData.name; exportPick.open() } }
                            LcButton {
                                objectName: "job-delete-" + jobRow.index
                                icon: "trash-2"; size: "sm"; variant: "ghost"
                                lock: jobRow.runs ? "Läuft gerade" : jobRow.waiting ? "Steht in der Warteschlange" : ""
                                tip: "Löschen"
                                onClicked: Start.deleteSaved(jobRow.modelData.name)
                            }
                        }
                    }
                }
            }
        }
    }

    FileDialog {
        id: uploadPick
        title: "G-Code hochladen"
        nameFilters: ["G-Code (*.gcode *.gc *.nc)"]
        onAccepted: Start.uploadFile(selectedFile.toString())
    }
    FileDialog {
        id: exportPick
        property string jobName
        title: "G-Code exportieren"
        fileMode: FileDialog.SaveFile
        nameFilters: ["G-Code (*.gcode)"]
        onAccepted: Start.exportSaved(jobName, selectedFile.toString())
    }
}
