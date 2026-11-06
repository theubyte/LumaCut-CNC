import QtQuick
import LumaCut

// The work area from the door, origin at the back left: head, and the part that is never lasered (park corner or strip).
Item {
    id: root
    objectName: "bed-mini"
    implicitHeight: 150
    readonly property real s: Math.min(width / Machine.bedWidth, height / Machine.bedHeight)
    Rectangle {
        id: bed
        anchors.centerIn: parent
        width: Machine.bedWidth * root.s
        height: Machine.bedHeight * root.s
        color: Theme.canvas
        border.width: 1
        border.color: Theme.line2
        radius: 2
        Rectangle {
            objectName: "bed-blocked"
            x: parent.width - width
            width: Math.min(parent.width, Machine.parkX * root.s)
            height: Machine.parkY * root.s
            color: Theme.park
            border.width: 1
            border.color: Qt.alpha(Theme.bad, .5)
        }
        LcText {
            text: Machine.blockedBandY > 0 ? "gesperrt bis Y " + Fmt.trim(Machine.blockedBandY, 0) : "Park-Ecke"
            kind: "small"
            font.pixelSize: Theme.fsXs
            color: Theme.bad
            visible: Machine.parkY * root.s > 14
            x: parent.width - width - 5
            y: (Machine.parkY * root.s - height) / 2
        }
        Rectangle {
            visible: Machine.hasPosition
            x: Machine.workX * root.s - width / 2
            y: Machine.workY * root.s - height / 2
            width: 9; height: 9; radius: 4.5
            color: Theme.accent
            border.width: 2
            border.color: Theme.surface
        }
    }
}
