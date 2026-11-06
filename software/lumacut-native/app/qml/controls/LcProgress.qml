import QtQuick
import LumaCut

// Thin progress bar. value 0..1.
Rectangle {
    property real value: 0
    implicitHeight: 6
    implicitWidth: 120
    radius: 3
    color: Theme.line2
    clip: true
    Rectangle {
        height: parent.height
        width: Math.max(0, Math.min(1, parent.value)) * parent.width
        radius: 3
        color: Theme.accent
        Behavior on width { NumberAnimation { duration: Theme.tMed } }
    }
}
