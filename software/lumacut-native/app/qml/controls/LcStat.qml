import QtQuick
import QtQuick.Layouts
import LumaCut

// Label over a value. tone: "", ok, warn, bad. mono: numbers in the mono face. large: position readout.
ColumnLayout {
    id: root
    property string label
    property string value
    property string tone
    property bool mono: true
    property bool large: false
    property alias valueName: val.objectName
    spacing: 1
    LcText { text: root.label; kind: "smallMuted"; font.weight: root.large ? Font.DemiBold : Font.Normal; Layout.fillWidth: true; elide: Text.ElideRight }
    LcText {
        id: val
        text: root.value
        kind: root.large ? "monoLg" : root.mono ? "mono" : "body"
        font.weight: root.large ? Font.DemiBold : Font.Medium
        color: root.tone === "ok" ? Theme.ok : root.tone === "warn" ? Theme.warn : root.tone === "bad" ? Theme.bad : Theme.text
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
}
