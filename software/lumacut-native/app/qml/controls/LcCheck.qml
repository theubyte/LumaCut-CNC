import QtQuick
import LumaCut

// Checkbox with label. checked is yours: react to toggled(on).
Item {
    id: root
    property bool checked: false
    property string text
    signal toggled(bool on)
    implicitWidth: box.width + (text.length ? 7 + label.implicitWidth : 0)
    implicitHeight: Math.max(18, label.implicitHeight)
    activeFocusOnTab: true
    opacity: enabled ? 1 : .5
    Keys.onPressed: (e) => { if (e.key === Qt.Key_Space) { toggled(!checked); e.accepted = true } }
    Rectangle {
        id: box
        width: 15; height: 15; radius: 4
        anchors.verticalCenter: parent.verticalCenter
        color: root.checked ? Theme.accent : Theme.surface
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus || root.checked ? Theme.accent : area.containsMouse ? Theme.faint : Theme.line2
        LcIcon { anchors.centerIn: parent; visible: root.checked; name: "check"; size: 12; width: 12; height: 12; strokeWidth: 3; color: Theme.accentInk }
    }
    LcText { id: label; text: root.text; visible: root.text.length > 0; x: box.width + 7; width: root.width > root.implicitWidth ? root.width - x : implicitWidth; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.WordWrap }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.toggled(!root.checked) }
}
