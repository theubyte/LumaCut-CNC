import QtQuick
import QtQuick.Layouts
import LumaCut

// Label above a control, optional hint below: LcField { label: "Stärke"; LcNumber { ... } }. The control gets the full width.
ColumnLayout {
    id: root
    property string label
    property string hint
    default property alias content: holder.data
    spacing: 3
    LcText { visible: root.label.length > 0; text: root.label; kind: "smallMuted"; Layout.fillWidth: true; elide: Text.ElideRight }
    Item {
        id: holder
        Layout.fillWidth: true
        implicitHeight: children.length ? children[0].implicitHeight : 0
        implicitWidth: children.length ? children[0].implicitWidth : 0
        onChildrenChanged: { for (let i = 0; i < children.length; i++) children[i].width = Qt.binding(() => holder.width) }
    }
    LcText { visible: root.hint.length > 0; text: root.hint; kind: "smallFaint"; font.pixelSize: Theme.fsXs; Layout.fillWidth: true; wrapMode: Text.WordWrap }
}
