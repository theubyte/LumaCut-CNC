import QtQuick
import LumaCut

// On/off switch. on is yours: react to toggled(v). lock: sentence why it is locked, also the tooltip.
Rectangle {
    id: root
    property bool on: false
    property string lock
    readonly property bool active: enabled && !lock
    signal toggled(bool v)
    implicitWidth: 38
    implicitHeight: 22
    radius: 11
    color: on ? Theme.accent : Theme.line2
    opacity: active ? 1 : .45
    activeFocusOnTab: true
    border.width: activeFocus ? 2 : 0
    border.color: Theme.text
    Behavior on color { ColorAnimation { duration: Theme.tMed } }
    Keys.onPressed: (e) => { if (active && e.key === Qt.Key_Space) { toggled(!on); e.accepted = true } }
    Rectangle {
        width: 18; height: 18; radius: 9; y: 2
        x: root.on ? 18 : 2
        color: "white"
        Behavior on x { NumberAnimation { duration: Theme.tMed; easing.type: Easing.OutCubic } }
    }
    MouseArea {
        id: area; anchors.fill: parent; hoverEnabled: true
        cursorShape: root.active ? Qt.PointingHandCursor : Qt.ForbiddenCursor
        onClicked: if (root.active) root.toggled(!root.on)
    }
    LcTip { shown: area.containsMouse; text: root.lock }
}
