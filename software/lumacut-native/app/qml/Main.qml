import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    objectName: "mainWindow"
    width: 1440; height: 900
    minimumWidth: 1000; minimumHeight: 640
    visible: false   // main.cpp shows it after setup
    title: "LumaCut Studio"
    flags: Qt.Window | Qt.FramelessWindowHint
    color: Theme.bg
    property string dest: "motiv"
    font.family: Theme.font
    font.pixelSize: Theme.fsMd

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        TopBar { Layout.fillWidth: true; Layout.preferredHeight: Theme.topbar; z: 200; window: win }
        RowLayout {
            spacing: 0
            Rail {
                Layout.fillHeight: true; Layout.preferredWidth: Theme.rail
                current: win.dest
                onNavigate: (key) => win.dest = key
            }
            Loader {
                objectName: "mainView"
                Layout.fillWidth: true; Layout.fillHeight: true
                sourceComponent: win.dest === "start" ? probe : placeholder
            }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: Theme.statusbar
            color: Theme.surface
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Text {
                anchors.verticalCenter: parent.verticalCenter; x: Theme.sp3
                text: "Grundgerüst, keine Maschine verbunden"
                color: Theme.muted; font.pixelSize: Theme.fsSm; font.family: Theme.font
            }
        }
    }
    Component { id: probe; GpuProbe {} }
    Component { id: placeholder; Placeholder { title: win.dest } }
}
