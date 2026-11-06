import QtQuick
import QtQuick.Layouts
import LumaCut

// Position in work coordinates, state, address. The slot in the middle belongs to the open view: Shell has no say in it.
Rectangle {
    objectName: "statusBar"
    color: Theme.surface
    Rectangle { width: parent.width; height: 1; color: Theme.line }
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: Theme.sp3; anchors.rightMargin: Theme.sp3
        spacing: Theme.sp4
        LcText {
            objectName: "status-pos"
            text: Machine.hasPosition ? "X " + Fmt.de(Machine.workX) + "  Y " + Fmt.de(Machine.workY) + "  Z " + Fmt.de(Machine.z) : "X –  Y –  Z –"
            kind: "mono"; color: Theme.muted; font.pixelSize: Theme.fsSm
        }
        LcText { objectName: "status-state"; text: Machine.stateText; kind: "smallMuted" }
        LcText { visible: Machine.laserArmed; text: "LASER SCHARF"; kind: "small"; color: Theme.bad; font.weight: Font.DemiBold }
        Item { Layout.fillWidth: true }
        LcText { objectName: "status-url"; text: Machine.online ? Pi.shortUrl : "getrennt"; kind: "smallMuted" }
    }
}
