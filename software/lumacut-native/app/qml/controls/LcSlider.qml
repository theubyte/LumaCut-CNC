import QtQuick
import QtQuick.Layouts
import LumaCut

// Track with a number field. moved(v) while dragging, committed() on release and after typing a number.
RowLayout {
    id: root
    property real value: 0
    property real min: 0
    property real max: 100
    property real step: 1
    property int digits: 0
    property string unit
    property bool showNumber: true
    signal moved(real v)
    signal committed()
    spacing: Theme.sp2
    opacity: enabled ? 1 : .5
    implicitHeight: Theme.hControl

    function _snap(v) { const s = Math.round((v - min) / step) * step + min; return Math.min(max, Math.max(min, +s.toFixed(6))) }
    Item {
        id: track
        Layout.fillWidth: true
        Layout.minimumWidth: 40
        implicitHeight: 18
        activeFocusOnTab: true
        readonly property real frac: root.max > root.min ? (root.value - root.min) / (root.max - root.min) : 0
        Keys.onPressed: (e) => {
            let d = 0
            if (e.key === Qt.Key_Left || e.key === Qt.Key_Down) d = -1
            if (e.key === Qt.Key_Right || e.key === Qt.Key_Up) d = 1
            if (d) { root.moved(root._snap(root.value + d * root.step * (e.modifiers & Qt.ShiftModifier ? 10 : 1))); root.committed(); e.accepted = true }
        }
        Rectangle { y: (parent.height - height) / 2; width: parent.width; height: 4; radius: 2; color: Theme.surface3 }
        Rectangle { y: (parent.height - height) / 2; width: track.frac * parent.width; height: 4; radius: 2; color: Theme.accent }
        Rectangle {
            width: 14; height: 14; radius: 7
            x: track.frac * (parent.width - width); y: (parent.height - height) / 2
            color: Theme.accent
            border.width: track.activeFocus ? 2 : 0
            border.color: Theme.text
            scale: mouse.pressed || mouse.containsMouse ? 1.14 : 1
            Behavior on scale { NumberAnimation { duration: Theme.tFast } }
        }
        MouseArea {
            id: mouse
            anchors.fill: parent
            anchors.margins: -2
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            preventStealing: true
            function take(x) { root.moved(root._snap(root.min + Math.min(1, Math.max(0, (x - 9) / (track.width - 14))) * (root.max - root.min))) }
            onPressed: (m) => take(m.x)
            onPositionChanged: (m) => { if (pressed) take(m.x) }
            onReleased: root.committed()
        }
    }
    LcNumber {
        visible: root.showNumber
        objectName: root.objectName.length ? root.objectName + "-num" : ""
        Layout.preferredWidth: 76
        value: root.value
        min: root.min; max: root.max; step: root.step; digits: root.digits; unit: root.unit
        onEdited: (v) => { root.moved(v); root.committed() }
    }
}
