import QtQuick
import QtQuick.Layouts
import LumaCut

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
        NavButton { key: "material"; label: "Material"; icon: "layers-3"; kbd: "1" }
        NavButton { key: "motiv"; label: "Motiv"; icon: "pencil"; kbd: "2" }
        NavButton { key: "start"; label: "Starten"; icon: "play"; kbd: "3" }
        Rectangle { Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 36; Layout.preferredHeight: 1; Layout.topMargin: 6; Layout.bottomMargin: 6; color: Theme.line }
        NavButton { key: "platine"; label: "Platine"; icon: "circuit-board"; kbd: "4" }
        NavButton { key: "werkstatt"; label: "Werkstatt"; icon: "hammer"; kbd: "5" }
        NavButton { key: "maschine"; label: "Maschine"; icon: "cog"; kbd: "6" }
        Item { Layout.fillHeight: true }
        NavButton { key: "optionen"; label: "Optionen"; icon: "settings"; kbd: "" }
    }
    component NavButton: Rectangle {
        id: nav
        property string key
        property string label
        property string icon
        property string kbd
        readonly property bool on: rail.current === key
        objectName: "nav-" + key
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: 64; Layout.preferredHeight: 56
        radius: Theme.rLg
        color: on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.tFast } }
        activeFocusOnTab: true
        border.width: activeFocus ? 2 : 0
        border.color: Theme.accent
        Keys.onPressed: (e) => { if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) { rail.navigate(key); e.accepted = true } }
        Column {
            anchors.centerIn: parent
            spacing: 3
            LcIcon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: nav.icon; size: 20; width: 20; height: 20; strokeWidth: 1.8
                color: nav.on ? Theme.accent : area.containsMouse ? Theme.text : Theme.muted
            }
            LcText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: nav.label
                color: nav.on ? Theme.accent : area.containsMouse ? Theme.text : Theme.muted
                font.pixelSize: Theme.fsXs
                font.weight: nav.on ? Font.DemiBold : Font.Medium
            }
        }
        MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rail.navigate(nav.key) }
        LcTip { side: "right"; shown: area.containsMouse; text: nav.kbd.length ? nav.label + " (Strg+" + nav.kbd + ")" : nav.label }
    }
}
