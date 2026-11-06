import QtQuick
import QtQuick.Layouts
import LumaCut

// Progress across the top while a job runs, with Abbrechen (no go needed to stop).
Rectangle {
    id: strip
    objectName: "jobstrip"
    readonly property var job: Machine.jobInfo
    visible: job.active === true
    implicitHeight: visible ? 40 : 0
    color: Qt.tint(Theme.surface, Theme.accentSoft)
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: Theme.sp4; anchors.rightMargin: Theme.sp4
        spacing: Theme.sp3
        LcButton { objectName: "job-file"; text: strip.job.file || ""; variant: "ghost"; size: "sm"; onClicked: Shell.navigate("start") }
        LcChip { objectName: "job-phase"; text: strip.job.phase || ""; tone: "accent" }
        LcProgress { Layout.fillWidth: true; value: (strip.job.percent || 0) / 100 }
        LcText { objectName: "job-percent"; text: Fmt.de(strip.job.percent || 0, 0) + " %"; kind: "muted"; tnum: true }
        LcButton { objectName: "job-abort"; text: "Abbrechen"; size: "sm"; onClicked: MachineActions.run("abort") }
    }
}
