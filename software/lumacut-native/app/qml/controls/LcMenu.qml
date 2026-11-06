import QtQuick
import QtQuick.Effects
import LumaCut

// Dropdown or context menu in Shell.overlay. Declare it anywhere, then menu.openAt(item) (below the item) or menu.popup(sceneX, sceneY).
// items: [{ label, icon?, kbd?, disabled?, separator?, action: function() {} }]. Entries are named <objectName>-<index>.
Item {
    id: root
    property var items: []
    property bool open: false
    property real _x: 0
    property real _y: 0
    signal closed()
    function requestClose() { open = false }
    function popup(sceneX, sceneY) {
        const p = Shell.overlay.mapFromItem(null, sceneX, sceneY)
        _x = p.x; _y = p.y; open = true
    }
    function openAt(item) {
        const p = item.mapToItem(null, 0, item.height + 4)
        popup(p.x, p.y)
    }
    parent: Shell.overlay
    anchors.fill: parent
    visible: open
    z: 150
    onOpenChanged: { if (open) Shell.pushModal(root); else { Shell.popModal(root); closed() } }
    Component.onDestruction: Shell.popModal(root)
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onPressed: root.open = false; onWheel: (w) => { root.open = false; w.accepted = false } }
    RectangularShadow { anchors.fill: box; offset.y: 4; blur: 14; radius: box.radius; color: Theme.shadowSoft }
    Rectangle {
        id: box
        x: Math.max(Theme.sp2, Math.min(root._x, root.width - width - Theme.sp2))
        y: Math.max(Theme.sp2, Math.min(root._y, root.height - height - Theme.sp2))
        width: Math.max(200, col.implicitWidth + 8)
        height: col.implicitHeight + 8
        radius: Theme.rLg
        color: Theme.surface
        border.width: 1
        border.color: Theme.line
        Column {
            id: col
            x: 4; y: 4
            Repeater {
                model: root.items
                Item {
                    id: entry
                    required property var modelData
                    required property int index
                    objectName: root.objectName.length && !modelData.separator ? root.objectName + "-" + index : ""
                    width: box.width - 8
                    height: modelData.separator ? 9 : 30
                    implicitWidth: modelData.separator ? 0 : 9 + (modelData.icon ? 23 : 0) + label.implicitWidth + (modelData.kbd ? 24 + kbd.implicitWidth : 0) + 9
                    Rectangle { visible: !!entry.modelData.separator; x: 6; width: parent.width - 12; y: 4; height: 1; color: Theme.line }
                    Rectangle {
                        visible: !entry.modelData.separator
                        anchors.fill: parent
                        radius: Theme.rSm
                        color: area.containsMouse && !entry.modelData.disabled ? Theme.surface3 : "transparent"
                        opacity: entry.modelData.disabled ? .45 : 1
                        LcIcon { visible: !!entry.modelData.icon; name: entry.modelData.icon || ""; size: 15; width: 15; height: 15; color: Theme.muted; x: 9; anchors.verticalCenter: parent.verticalCenter }
                        LcText { id: label; text: entry.modelData.label || ""; x: entry.modelData.icon ? 32 : 9; anchors.verticalCenter: parent.verticalCenter }
                        LcText { id: kbd; text: entry.modelData.kbd || ""; kind: "smallFaint"; font.family: Theme.mono; anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter }
                        MouseArea {
                            id: area; anchors.fill: parent; hoverEnabled: true
                            cursorShape: entry.modelData.disabled ? Qt.ForbiddenCursor : Qt.PointingHandCursor
                            onClicked: {
                                if (entry.modelData.disabled) return
                                const act = entry.modelData.action
                                root.open = false
                                if (act) act()
                            }
                        }
                    }
                }
            }
        }
    }
}
