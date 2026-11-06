import QtQuick
import QtQuick.Layouts

// Always on top of every dialog: NOT-AUS stays reachable. In the skeleton the button only prints; the Pi client wires it.
Rectangle {
    id: bar
    objectName: "topBar"
    property var window
    signal estop()
    color: Theme.surface
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    DragHandler {
        target: null
        onActiveChanged: if (active) bar.window.startSystemMove()
    }
    TapHandler {
        acceptedButtons: Qt.LeftButton
        onDoubleTapped: bar.window.visibility === 4 ? bar.window.showNormal() : bar.window.showMaximized()
    }
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: Theme.sp3
        spacing: Theme.sp3
        Rectangle {
            Layout.preferredWidth: 22; Layout.preferredHeight: 22; radius: 6; color: Theme.accent
            Text { anchors.centerIn: parent; text: "⚡"; color: Theme.accentInk; font.pixelSize: 12 }
        }
        Text { text: "LumaCut"; color: Theme.text; font.family: Theme.fontDisplay; font.pixelSize: Theme.fsLg; font.weight: Font.DemiBold }
        Item { Layout.fillWidth: true }
        Rectangle {
            objectName: "estop"
            Layout.preferredHeight: 34; Layout.preferredWidth: 116; radius: 8
            color: estopArea.containsMouse ? Theme.estopHover : Theme.estop
            Text { anchors.centerIn: parent; text: "NOT-AUS"; color: "white"; font.pixelSize: Theme.fsMd; font.weight: Font.Bold; font.letterSpacing: 0.6 }
            MouseArea { id: estopArea; anchors.fill: parent; hoverEnabled: true; onClicked: bar.estop() }
        }
        Row {
            Layout.fillHeight: true
            Repeater {
                model: [
                    { key: "min", sym: "—" },
                    { key: "max", sym: "□" },
                    { key: "close", sym: "✕" }
                ]
                Rectangle {
                    required property var modelData
                    objectName: "win-" + modelData.key
                    width: 44; height: bar.height
                    color: area.containsMouse ? (modelData.key === "close" ? "#d7262f" : Theme.surface3) : "transparent"
                    Text { anchors.centerIn: parent; text: parent.modelData.sym; color: area.containsMouse && parent.modelData.key === "close" ? "white" : Theme.muted; font.pixelSize: 12 }
                    MouseArea {
                        id: area; anchors.fill: parent; hoverEnabled: true
                        onClicked: {
                            if (parent.modelData.key === "min") bar.window.showMinimized();
                            else if (parent.modelData.key === "max") bar.window.visibility === 4 ? bar.window.showNormal() : bar.window.showMaximized();
                            else bar.window.close();
                        }
                    }
                }
            }
        }
    }
}
