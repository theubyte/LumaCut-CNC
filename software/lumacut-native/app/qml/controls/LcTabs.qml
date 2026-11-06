import QtQuick
import LumaCut

// Tab strip across a view. tabs: [{ value, label }]. react to activated(v). Parts are named <objectName>-<value>.
Rectangle {
    id: root
    property var tabs: []
    property var value
    signal activated(var v)
    color: Theme.surface
    implicitHeight: 40
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    Row {
        x: Theme.sp4
        height: parent.height
        spacing: 2
        Repeater {
            model: root.tabs
            Item {
                id: tab
                required property var modelData
                readonly property bool on: root.value === modelData.value
                objectName: root.objectName.length ? root.objectName + "-" + modelData.value : ""
                height: parent.height
                width: label.implicitWidth + 24
                activeFocusOnTab: true
                Keys.onPressed: (e) => { if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) { root.activated(modelData.value); e.accepted = true } }
                LcText { id: label; anchors.centerIn: parent; text: tab.modelData.label; font.weight: tab.on ? Font.DemiBold : Font.Medium; color: tab.on || area.containsMouse ? Theme.text : Theme.muted }
                Rectangle { x: 10; width: parent.width - 20; height: 2; radius: 1; y: parent.height - 2; color: Theme.accent; visible: tab.on }
                Rectangle { anchors.fill: parent; anchors.margins: 4; radius: Theme.rSm; color: "transparent"; border.width: 2; border.color: Theme.accent; visible: tab.activeFocus }
                MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.activated(tab.modelData.value) }
            }
        }
    }
}
