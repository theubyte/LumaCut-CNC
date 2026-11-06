import QtQuick
import QtQuick.Effects
import LumaCut

// Small panel in Shell.overlay, below an item. Closes on Esc and on a click elsewhere.
Item {
    id: root
    property bool open: false
    property int popWidth: 240
    default property alias content: holder.data
    property real _x: 0
    property real _y: 0
    function requestClose() { open = false }
    function openAt(item) {
        const p = item.mapToItem(Shell.overlay, 0, item.height + 6)
        _x = p.x; _y = p.y
        open = true
    }
    parent: Shell.overlay
    anchors.fill: parent
    visible: open
    z: 150
    onOpenChanged: { if (open) Shell.pushModal(root); else Shell.popModal(root) }
    Component.onDestruction: Shell.popModal(root)
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onPressed: root.open = false }
    RectangularShadow { anchors.fill: box; offset.y: 4; blur: 14; radius: box.radius; color: Theme.shadowSoft }
    Rectangle {
        id: box
        x: Math.max(Theme.sp2, Math.min(root._x, root.width - width - Theme.sp2))
        y: Math.max(Theme.sp2, Math.min(root._y, root.height - height - Theme.sp2))
        width: root.popWidth
        height: holder.childrenRect.height + 2 * Theme.sp3
        radius: Theme.rLg
        color: Theme.surface
        border.width: 1
        border.color: Theme.line
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
        Item {
            id: holder
            x: Theme.sp3; y: Theme.sp3
            width: parent.width - 2 * Theme.sp3
        }
    }
}
