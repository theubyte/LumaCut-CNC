import QtQuick
import QtQuick.Layouts
import LumaCut

// The go before every laser or motion job. Enter must NOT confirm: the focus is on "Abbrechen", and the start button ignores
// Enter and Space. Starting takes a deliberate click or Alt+S. An answer to another question is never a go.
LcDialog {
    id: dlg
    objectName: "goDialog"
    open: MachineActions.goOpen
    title: MachineActions.goTitle
    dialogWidth: 460
    initialFocus: cancel
    readonly property bool laser: MachineActions.goKind === "laser"
    onRejected: MachineActions.answerGo(false)
    Connections {
        target: Shell
        enabled: dlg.open
        function onGoKey() { MachineActions.answerGo(true) }
    }
    LcText { objectName: "go-detail"; visible: text.length > 0; text: MachineActions.goDetail; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.sp2
        Repeater {
            model: dlg.laser ? [["hand", "Hände raus"], ["panel-top", "Deckel zu"], ["glasses", "Brille auf"]] : [["hand", "Hände raus"], ["move", "Fahrweg frei"]]
            Rectangle {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitHeight: 70
                radius: Theme.rLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.line
                Column {
                    anchors.centerIn: parent
                    spacing: 6
                    LcIcon { anchors.horizontalCenter: parent.horizontalCenter; name: modelData[0]; size: 20; width: 20; height: 20; color: Theme.text }
                    LcText { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; font.weight: Font.DemiBold }
                }
            }
        }
    }
    footer: [
        LcButton { id: cancel; objectName: "go-cancel"; text: "Abbrechen"; size: "lg"; onClicked: MachineActions.answerGo(false) },
        LcButton {
            objectName: "go-confirm"
            text: MachineActions.goOkLabel
            size: "lg"
            variant: dlg.laser ? "danger" : "primary"
            icon: dlg.laser ? "zap" : "move"
            keyActivation: false
            onClicked: MachineActions.answerGo(true)
        }
    ]
}
