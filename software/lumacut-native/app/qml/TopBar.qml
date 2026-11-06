import QtQuick
import QtQuick.Layouts
import LumaCut

// Stacked above every dialog: NOT-AUS stays reachable. Empty parts of the bar drag the window (WindowChrome).
Rectangle {
    id: bar
    objectName: "topBar"
    property var window
    property var chrome
    property alias maxButton: maxBtn
    color: Theme.surface
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

    RowLayout {
        anchors.fill: parent; anchors.leftMargin: Theme.sp3
        spacing: Theme.sp3
        Row {
            spacing: Theme.sp2
            Layout.alignment: Qt.AlignVCenter
            Rectangle {
                width: 22; height: 22; radius: 6; color: Theme.accent
                anchors.verticalCenter: parent.verticalCenter
                LcIcon { anchors.centerIn: parent; name: "zap"; size: 14; width: 14; height: 14; color: Theme.accentInk }
            }
            LcText { text: "LumaCut"; color: Theme.text; font.family: Theme.fontDisplay; font.pixelSize: Theme.fsLg; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
        }
        LcText {
            objectName: "projectTitle"
            text: Shell.projectTitle + (Shell.projectDirty ? " •" : "")
            kind: "faint"
            elide: Text.ElideRight
            Layout.maximumWidth: 360
        }
        Item { Layout.fillWidth: true }
        LcChip {
            objectName: "conn-chip"
            text: Machine.chip.text
            tone: Machine.chip.tone
            icon: Machine.online ? "wifi" : "wifi-off"
            clickable: true
            tip: "Zur Maschine"
            onClicked: Shell.navigate("maschine")
        }
        LcButton {
            objectName: "estop-reset"
            visible: Machine.latched
            text: "Not-Aus quittieren"
            size: "sm"
            onClicked: MachineActions.run("estop_reset")
        }
        Rectangle {
            id: estop
            objectName: "estop"
            Layout.preferredHeight: 34
            implicitWidth: estopRow.implicitWidth + 32
            radius: 8
            color: estopArea.containsMouse ? Theme.estopHover : Theme.estop
            Behavior on color { ColorAnimation { duration: Theme.tFast } }
            Rectangle {
                anchors.fill: parent; anchors.margins: -3
                radius: 11; color: "transparent"; border.width: 3; border.color: Theme.badSoft
                visible: estopArea.containsMouse || Machine.latched
                SequentialAnimation on opacity {
                    running: Machine.latched; loops: Animation.Infinite
                    NumberAnimation { to: .25; duration: 600 }
                    NumberAnimation { to: 1; duration: 600 }
                }
            }
            Row {
                id: estopRow
                anchors.centerIn: parent
                spacing: 7
                LcIcon { name: "octagon-x"; size: 18; width: 18; height: 18; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                LcText { text: "NOT-AUS"; color: "white"; font.weight: Font.Bold; font.letterSpacing: 0.6; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea { id: estopArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: MachineActions.estop() }
            LcTip { shown: estopArea.containsMouse; text: "NOT-AUS (Taste Pause)" }
        }
        Row {
            Layout.fillHeight: true
            WinButton { objectName: "win-min"; icon: "minus"; onClicked: bar.window.showMinimized() }
            WinButton {
                id: maxBtn
                objectName: "win-max"
                icon: bar.chrome && bar.chrome.maximized ? "copy" : "square"
                iconSize: 12
                nativeHover: bar.chrome ? bar.chrome.maxHovered : false
                onClicked: bar.chrome.toggleMaximize()
            }
            WinButton { objectName: "win-close"; icon: "x"; danger: true; iconSize: 16; onClicked: bar.window.close() }
        }
    }

    component WinButton: Item {
        id: wb
        property string icon
        property int iconSize: 15
        property bool danger: false
        property bool nativeHover: false
        signal clicked()
        readonly property bool hot: wbArea.containsMouse || nativeHover
        width: 44; height: bar.height
        Rectangle { anchors.fill: parent; anchors.bottomMargin: 1; color: wb.hot ? (wb.danger ? "#d7262f" : Theme.surface3) : "transparent" }
        LcIcon { anchors.centerIn: parent; name: wb.icon; size: wb.iconSize; width: wb.iconSize; height: wb.iconSize; color: wb.hot && wb.danger ? "white" : wb.hot ? Theme.text : Theme.muted }
        MouseArea { id: wbArea; anchors.fill: parent; hoverEnabled: true; onClicked: wb.clicked() }
    }
}
