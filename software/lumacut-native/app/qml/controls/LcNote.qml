import QtQuick
import QtQuick.Layouts
import LumaCut

// Hint box. tone: info, warn, bad, ok. Use in a layout with Layout.fillWidth: true.
Rectangle {
    id: root
    property string tone: "info"
    property string text
    radius: Theme.rMd
    color: tone === "warn" ? Theme.warnSoft : tone === "bad" ? Theme.badSoft : tone === "ok" ? Theme.okSoft : Theme.infoSoft
    implicitWidth: label.implicitWidth + 44
    implicitHeight: Math.max(label.implicitHeight, 16) + 18
    LcIcon {
        x: 11; y: 11
        width: 15; height: 15; size: 15
        name: root.tone === "warn" ? "alert-triangle" : root.tone === "bad" ? "x-circle" : root.tone === "ok" ? "check-circle-2" : "info"
        color: root.tone === "warn" ? Theme.warn : root.tone === "bad" ? Theme.bad : root.tone === "ok" ? Theme.ok : Theme.info
    }
    LcText {
        id: label
        x: 34; y: 9
        width: root.width - x - 11
        text: root.text
        wrapMode: Text.WordWrap
    }
}
