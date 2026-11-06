import QtQuick
import LumaCut

// Small status pill. tone: "" (neutral), ok, warn, bad, info, accent. icon: Lucide name. clickable: emits clicked().
Rectangle {
    id: root
    property string text
    property string tone
    property string icon
    property bool clickable: false
    property string tip
    signal clicked()
    readonly property color ink: tone === "ok" ? Theme.ok : tone === "warn" ? Theme.warn : tone === "bad" ? Theme.bad : tone === "info" ? Theme.info : tone === "accent" ? Theme.accent : Theme.muted
    radius: height / 2
    color: tone === "ok" ? Theme.okSoft : tone === "warn" ? Theme.warnSoft : tone === "bad" ? Theme.badSoft : tone === "info" ? Theme.infoSoft : tone === "accent" ? Theme.accentSoft : Theme.surface3
    implicitHeight: 22
    implicitWidth: row.implicitWidth + 16
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 5
        LcIcon { visible: root.icon.length > 0; name: root.icon; size: 13; width: 13; height: 13; color: root.ink; anchors.verticalCenter: parent.verticalCenter }
        LcText { text: root.text; kind: "small"; color: root.ink; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
    }
    MouseArea { id: area; anchors.fill: parent; enabled: root.clickable; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.clicked() }
    LcTip { shown: area.containsMouse; text: root.tip }
}
