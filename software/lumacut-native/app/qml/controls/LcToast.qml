import QtQuick
import QtQuick.Effects
import LumaCut

// The toast stack, one instance in Main.qml. Anywhere else: Toast.show("Text", "ok"). Never takes a click away from what lies below.
Column {
    id: root
    spacing: Theme.sp2
    width: 420
    Repeater {
        model: Toast.items
        Item {
            id: t
            required property var modelData
            anchors.right: parent ? parent.right : undefined
            width: Math.min(root.width, label.implicitWidth + 30)
            height: label.implicitHeight + 18
            objectName: "toast-" + modelData.tone
            property alias text: label.text
            RectangularShadow { anchors.fill: bg; offset.y: 4; blur: 14; radius: bg.radius; color: Theme.shadowSoft }
            Rectangle {
                id: bg
                anchors.fill: parent
                radius: Theme.rMd
                color: Theme.surface
                border.width: 1
                border.color: Theme.line
                Rectangle {
                    width: 3; height: parent.height - 2; x: 0; y: 1
                    radius: 1.5
                    color: t.modelData.tone === "ok" ? Theme.ok : t.modelData.tone === "bad" ? Theme.bad : t.modelData.tone === "warn" ? Theme.warn : Theme.accent
                }
                LcText { id: label; x: 15; y: 9; width: Math.min(implicitWidth, root.width - 30); text: t.modelData.text; wrapMode: Text.WordWrap }
            }
        }
    }
}
