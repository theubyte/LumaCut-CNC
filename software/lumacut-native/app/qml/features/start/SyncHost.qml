import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import LumaCut

// Mounted once in Main.qml: starts the project sharing and shows its dialogs.
Item {
    id: host
    anchors.fill: parent
    Component.onCompleted: Sync.start()

    // Test handle: the driver has no way into a system file dialog.
    Item {
        objectName: "sync-api"
        function openNow(path) { return Sync.openLocalNow(path) }
        function openFrom(path) { Sync.openLocalFrom(path); return true }
        function saveTo(path) { return Sync.saveLocalTo(path) }
        function pushNow() { Sync.pushNow(); return true }
        function autosaveNow() { Sync.autosaveNow(); return true }
        function conflict() { return Sync.conflict }
        function baseRevision() { return Sync.baseRevision }
        function unsent() { return Sync.unsent }
        function filePath() { return Sync.filePath }
        function openDialog(mode) { if (mode === "save") Sync.saveProjectToPi(); else Sync.openProjectDialog(); return true }
        function projects() { return Sync.projects }
    }

    Connections {
        target: Sync
        function onPickSavePath(name) { savePick.currentFile = "file:///" + name; savePick.open() }
        function onPickOpenPath() { openPick.open() }
    }
    FileDialog {
        id: savePick
        title: "Projekt speichern"
        fileMode: FileDialog.SaveFile
        nameFilters: ["LumaCut-Projekt (*.lumacut)"]
        onAccepted: Sync.saveLocalTo(selectedFile.toString())
    }
    FileDialog {
        id: openPick
        title: "Projekt öffnen"
        nameFilters: ["LumaCut-Projekt (*.lumacut)"]
        onAccepted: Sync.openLocalNow(selectedFile.toString())
    }

    LcDialog {
        objectName: "conflictDialog"
        open: Sync.conflict
        title: "Projekt an einem anderen Gerät geändert"
        locked: true
        dialogWidth: 480
        initialFocus: keep
        LcText {
            objectName: "conflict-text"
            text: "Auf dem Pi liegt eine neuere Fassung des Projekts, und auch hier wurde geändert. Welche soll gelten? Die andere geht verloren, solange sie nicht gespeichert ist."
            kind: "muted"; wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        footer: [
            LcButton { id: keep; objectName: "conflict-keep"; text: "Diese Fassung behalten"; busy: Sync.busy; onClicked: Sync.resolveConflict(false) },
            LcButton { objectName: "conflict-take"; text: "Vom Pi übernehmen"; variant: "primary"; busy: Sync.busy; onClicked: Sync.resolveConflict(true) }
        ]
    }

    LcDialog {
        objectName: "recoveredDialog"
        open: Sync.recovered.title !== undefined
        title: "Ungesicherte Arbeit gefunden"
        dialogWidth: 440
        initialFocus: restore
        onRejected: Sync.discardAutosave()
        LcText {
            objectName: "recovered-text"
            text: "„" + (Sync.recovered.title || "") + "“ wurde zuletzt am " + (Sync.recovered.when || "") + " automatisch gesichert und nie gespeichert."
            kind: "muted"; wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        footer: [
            LcButton { objectName: "recovered-discard"; text: "Verwerfen"; onClicked: Sync.discardAutosave() },
            LcButton { id: restore; objectName: "recovered-restore"; text: "Wiederherstellen"; variant: "primary"; onClicked: Sync.restoreAutosave() }
        ]
    }

    LcDialog {
        id: projectDialog
        objectName: "projectDialog"
        open: Sync.dialogMode.length > 0
        readonly property bool saving: Sync.dialogMode === "save"
        readonly property var existing: {
            const n = nameInput.text.trim().toLowerCase()
            for (const p of Sync.projects) if (p.name.toLowerCase() === n) return p
            return null
        }
        readonly property bool nameOk: nameInput.text.trim().length >= 1 && nameInput.text.trim().length <= 80
        readonly property bool canSave: nameOk && !Sync.busy && Sync.projectsLoaded && !Sync.projectsError.length
        title: saving ? "Auf dem Pi speichern" : "Projekt vom Pi öffnen"
        dialogWidth: 520
        initialFocus: saving ? nameInput.input : closeButton
        onOpenChanged: if (open) nameInput.text = Document.title
        onRejected: Sync.closeDialog()
        function store() { if (canSave) Sync.saveNamed(nameInput.text) }

        LcField {
            visible: projectDialog.saving
            Layout.fillWidth: true
            label: "Name"
            hint: projectDialog.existing ? "Ein Projekt „" + projectDialog.existing.name + "“ gibt es schon: Speichern ersetzt es." : ""
            LcInput { id: nameInput; objectName: "project-name"; maxLength: 80; onAccepted: projectDialog.store() }
        }
        RowLayout {
            visible: Sync.projectsError.length > 0
            Layout.fillWidth: true
            LcText { text: Sync.projectsError; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcButton { objectName: "project-reload"; icon: "refresh-cw"; text: "Neu laden"; size: "sm"; onClicked: Sync.reloadProjects() }
        }
        LcText {
            visible: !Sync.projectsError.length && !Sync.projectsLoaded
            text: "Liste wird geladen …"
            kind: "muted"
        }
        LcText {
            objectName: "project-none"
            visible: !Sync.projectsError.length && Sync.projectsLoaded && !Sync.projects.length
            text: "Noch keine Projekte auf dem Pi." + (projectDialog.saving ? "" : " Speichere zuerst eines über „Auf dem Pi speichern“.")
            kind: "muted"; wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        LcText {
            visible: projectDialog.saving && Sync.projects.length > 0 && !Sync.projectsError.length
            text: "Schon auf dem Pi (Klick übernimmt den Namen)"
            kind: "smallMuted"
        }
        Column {
            objectName: "project-list"
            visible: Sync.projects.length > 0 && !Sync.projectsError.length
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: Sync.projects
                Rectangle {
                    required property var modelData
                    required property int index
                    objectName: "project-row-" + index
                    width: parent.width
                    height: rowCol.implicitHeight + Theme.sp1 * 2
                    radius: Theme.rSm
                    color: rowArea.containsMouse ? Theme.surface2 : "transparent"
                    MouseArea {
                        id: rowArea
                        objectName: "project-open-" + index
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { if (projectDialog.saving) nameInput.text = modelData.name; else Sync.openSaved(modelData) }
                    }
                    Column {
                        id: rowCol
                        x: Theme.sp2
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - x - Theme.hControlSm - Theme.sp2
                        spacing: 1
                        LcText { text: modelData.name; font.weight: Font.Medium; width: parent.width; elide: Text.ElideRight }
                        LcText { text: modelData.line; kind: "smallFaint"; font.pixelSize: Theme.fsXs; width: parent.width; elide: Text.ElideRight }
                    }
                    LcButton {
                        objectName: "project-delete-" + index
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.sp1
                        anchors.verticalCenter: parent.verticalCenter
                        icon: "trash-2"; size: "sm"; variant: "ghost"
                        tip: "„" + modelData.name + "“ löschen"
                        enabled: !Sync.busy
                        onClicked: Sync.deleteProject(modelData)
                    }
                }
            }
        }
        footer: [
            LcButton { id: closeButton; objectName: "project-close"; text: projectDialog.saving ? "Abbrechen" : "Schließen"; onClicked: Sync.closeDialog() },
            LcButton {
                objectName: "project-save"
                visible: projectDialog.saving
                variant: "primary"
                text: projectDialog.existing ? "Ersetzen" : "Speichern"
                enabled: projectDialog.canSave
                busy: Sync.busy
                onClicked: projectDialog.store()
            }
        ]
    }
}
