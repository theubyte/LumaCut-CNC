import QtQuick
import QtQuick.Layouts

// Same words and order as the Android app; Platine and Werkstatt are additions.
Rectangle {
    id: rail
    property string current
    signal navigate(string key)
    color: Theme.surface
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
    ColumnLayout {
        anchors.fill: parent; anchors.topMargin: Theme.sp2; anchors.bottomMargin: Theme.sp2
        spacing: 2
        Repeater {
            model: [ ["material", "Material"], ["motiv", "Motiv"], ["start", "Starten"], ["platine", "Platine"], ["werkstatt", "Werkstatt"], ["maschine", "Maschine"] ]
            Rectangle {
                required property var modelData
                objectName: "nav-" + modelData[0]
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 64; Layout.preferredHeight: 56; radius: Theme.rLg
                color: rail.current === modelData[0] ? Theme.accentSoft : (m.containsMouse ? Theme.surface3 : "transparent")
                Text {
                    anchors.centerIn: parent
                    text: parent.modelData[1]
                    color: rail.current === parent.modelData[0] ? Theme.accent : Theme.muted
                    font.pixelSize: Theme.fsXs; font.weight: rail.current === parent.modelData[0] ? Font.DemiBold : Font.Medium
                }
                MouseArea { id: m; anchors.fill: parent; hoverEnabled: true; onClicked: rail.navigate(parent.modelData[0]) }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
