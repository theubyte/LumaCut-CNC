import QtQuick
import QtQuick.Layouts
import LumaCut

// Surface with a border. Children stack in a ColumnLayout; padding and spacing set the rhythm. padding 0 for edge-to-edge content.
Rectangle {
    id: root
    property int padding: Theme.sp4
    property alias spacing: col.spacing
    default property alias content: col.data
    color: Theme.surface
    border.width: 1
    border.color: Theme.line
    radius: Theme.rLg
    implicitWidth: col.implicitWidth + 2 * padding
    implicitHeight: col.implicitHeight + 2 * padding
    ColumnLayout {
        id: col
        x: root.padding; y: root.padding
        width: root.width - 2 * root.padding
        spacing: Theme.sp3
    }
}
