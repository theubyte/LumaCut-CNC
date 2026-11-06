import QtQuick
import QtQuick.Layouts
import LumaCut

// Starten: left what the laser will do, right what speaks against it and the one big button. All logic is in StartController.
Item {
    id: root
    objectName: "view-Start"
    Component.onCompleted: Start.enter()
    Component.onDestruction: Start.leave()

    // Test handle: everything a file dialog or the driver's arguments cannot reach.
    Item {
        objectName: "start-api"
        function openProject(path) { return Sync.openLocalNow(path) }
        function saveProject(path) { return Sync.saveLocalTo(path) }
        function timings() { return Start.timings() }
        function checks() { return Start.checks }
        function jobs() { return Start.jobs }
        function queue() { return Start.queueItems }
        function layers() { return Start.layerRows }
        function title() { return Document.title }
        function dirty() { return Document.dirty }
        function revision() { return Number(Document.revision) }
        function setTitle(t) { Document.title = t; return true }
        function uploadFile(path) { Start.uploadFile(path); return true }
        function exportJob(a) { Start.exportSaved(a[0], a[1]); return true }
        function previewJob(n) { Start.previewSaved(n); return true }
        function enqueueJob(n) { Start.enqueueSaved(n); return true }
        function building() { return JobBuilder.building }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            spacing: 0
            StartPreview { Layout.fillWidth: true; Layout.fillHeight: true }
            StartDock { Layout.fillWidth: true }
        }
        StartSide {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.max(Theme.panel + Theme.sp6, Math.min(root.width * 0.27, Theme.panelWide))
        }
    }
}
