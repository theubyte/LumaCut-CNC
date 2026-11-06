import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LumaCut

ApplicationWindow {
    id: win
    objectName: "mainWindow"
    width: 1440; height: 900
    minimumWidth: 1000; minimumHeight: 640
    visible: false   // main.cpp shows it after setup
    title: "LumaCut Studio"
    flags: Qt.Window   // the native title bar is removed in WindowChrome, Qt must not treat this window as frameless
    color: Theme.bg
    font.family: Theme.font
    font.pixelSize: Theme.fsMd

    Binding { target: Theme; property: "pref"; value: AppSettings.theme }
    WindowChrome {
        id: nativeChrome
        titleBar: topBar
        maxButton: topBar.maxButton
        dark: Theme.dark
    }
    Component.onCompleted: {
        nativeChrome.window = win
        Shell.attachWindow(win)
        Shell.overlay = overlay
        Machine.start()
        Materials.load()
    }
    Connections { target: Shell; function onEstopKey() { MachineActions.estop() } }

    // Test handle for the driver: shell.setTheme("dark"), shell.resizeTo([1000, 640]).
    Item {
        id: shell
        objectName: "shell"
        anchors.fill: parent
        anchors.margins: nativeChrome.inset
        function setTheme(v) { AppSettings.theme = v; return v }
        function resizeTo(size) { win.showNormal(); win.width = size[0]; win.height = size[1]; return size }
        function isDark() { return Theme.dark }
        function machine(key) { return Machine.status[key] }
        function lastToast() { return Toast.lastText }
        function piUrl() { return Pi.baseUrl }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            TopBar { id: topBar; Layout.fillWidth: true; Layout.preferredHeight: Theme.topbar; z: 200; chrome: nativeChrome; window: win }
            JobStrip { Layout.fillWidth: true; z: 50 }
            RowLayout {
                spacing: 0
                Rail {
                    Layout.fillHeight: true; Layout.preferredWidth: Theme.rail
                    current: Shell.dest
                    onNavigate: (key) => Shell.navigate(key)
                }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    color: Theme.bg
                    Loader {
                        objectName: "mainView"
                        anchors.fill: parent
                        source: "features/" + ({material:"Material",motiv:"Motiv",start:"Start",platine:"Platine",werkstatt:"Werkstatt",maschine:"Maschine",optionen:"Optionen"})[Shell.dest] + "View.qml"
                    }
                }
            }
            StatusBar { Layout.fillWidth: true; Layout.preferredHeight: Theme.statusbar }
        }

        // Everything modal lives here, below the top bar: NOT-AUS stays reachable above every dialog.
        Item {
            id: overlay
            objectName: "overlay"
            anchors.fill: parent
            anchors.topMargin: Theme.topbar
            z: 100
            GoDialog {}
            LcConfirmHost {}
            LcToast {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.rightMargin: Theme.sp4
                anchors.bottomMargin: Theme.statusbar + Theme.sp3
                z: 200
            }
        }
    }
}
