import QtQuick
import QtQuick.Layouts
import LumaCut

// One line of the action list: icon, title, sentence or custom part below it, controls on the right.
RowLayout {
    id: root
    property string icon
    property string title
    property string sub
    property color subColor: Theme.muted
    property alias below: belowHolder.data
    default property alias controls: end.data
    spacing: Theme.sp3
    Layout.fillWidth: true
    Layout.minimumHeight: 48
    Rectangle {
        Layout.preferredWidth: 28; Layout.preferredHeight: 28
        Layout.alignment: Qt.AlignTop
        Layout.topMargin: 10
        radius: Theme.rMd
        color: Theme.surface3
        LcIcon { anchors.centerIn: parent; name: root.icon; size: 16; width: 16; height: 16; color: Theme.muted }
    }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        Layout.topMargin: 6; Layout.bottomMargin: 6
        spacing: 1
        LcText { text: root.title; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
        LcText { visible: root.sub.length > 0; text: root.sub; kind: "small"; color: root.subColor; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        Item {
            id: belowHolder
            visible: children.length > 0
            Layout.fillWidth: true
            Layout.topMargin: 5
            implicitHeight: children.length ? children[0].implicitHeight : 0
        }
    }
    Row {
        id: end
        spacing: 4
        Layout.alignment: Qt.AlignTop
        Layout.topMargin: Math.max(0, (48 - implicitHeight) / 2)
    }
}
