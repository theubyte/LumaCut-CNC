import QtQuick
import QtQuick.Layouts
import LumaCut

// Shows Confirm.ask(...). One instance in Main.qml. A plain question, never a go.
LcDialog {
    id: dlg
    objectName: "confirmDialog"
    open: Confirm.open
    title: Confirm.title
    dialogWidth: 440
    initialFocus: cancel
    onRejected: Confirm.answer(false)
    LcText { text: Confirm.body; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true; visible: text.length > 0 }
    footer: [
        LcButton { id: cancel; objectName: "confirm-cancel"; text: "Abbrechen"; onClicked: Confirm.answer(false) },
        LcButton { objectName: "confirm-ok"; text: Confirm.okLabel; variant: Confirm.danger ? "danger" : "primary"; onClicked: Confirm.answer(true) }
    ]
}
