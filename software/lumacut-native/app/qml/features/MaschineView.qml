import QtQuick
import QtQuick.Layouts
import LumaCut

// Tabs stay alive once opened; a hidden tab's camera preview stops by itself.
Item {
    id: root
    objectName: "view-Maschine"
    property string tab: { const t = AppSettings.value("maschineTab", "steuerung"); return ["steuerung", "kamera", "kalibrieren", "system"].includes(t) ? t : "steuerung" }
    readonly property int camFrames: kameraLoader.item ? kameraLoader.item.frames : 0
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        LcTabs {
            objectName: "m-tab"
            Layout.fillWidth: true
            tabs: [{ value: "steuerung", label: "Steuerung" }, { value: "kamera", label: "Kamera" }, { value: "kalibrieren", label: "Kalibrieren" }, { value: "system", label: "System" }]
            value: root.tab
            onActivated: (v) => { root.tab = v; AppSettings.setValue("maschineTab", v) }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Loader { anchors.fill: parent; active: root.tab === "steuerung" || item; visible: root.tab === "steuerung"; source: "maschine/MaschineSteuerung.qml" }
            Loader { id: kameraLoader; anchors.fill: parent; active: root.tab === "kamera" || item; visible: root.tab === "kamera"; source: "maschine/MaschineKamera.qml" }
            Loader { anchors.fill: parent; active: root.tab === "kalibrieren" || item; visible: root.tab === "kalibrieren"; source: "maschine/MaschineKalibrieren.qml" }
            Loader { anchors.fill: parent; active: root.tab === "system" || item; visible: root.tab === "system"; source: "maschine/MaschineSystem.qml" }
        }
    }
}
