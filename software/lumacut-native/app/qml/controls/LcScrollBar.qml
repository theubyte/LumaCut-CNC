import QtQuick
import QtQuick.Controls
import LumaCut

// Slim scroll bar for any Flickable: ScrollBar.vertical: LcScrollBar {}
ScrollBar {
    id: bar
    policy: size < 1 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
    minimumSize: .06
    padding: 2
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: bar.pressed || bar.hovered ? Theme.faint : Theme.line2
        opacity: bar.active || bar.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.tMed } }
    }
    background: Item {}
}
