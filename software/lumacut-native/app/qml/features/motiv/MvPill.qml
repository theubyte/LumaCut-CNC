import QtQuick
import LumaCut

// Small label on the stage. tone: accent, bad, warn, plain.
Rectangle {
    id: root
    property string text
    property string tone: "plain"
    width: label.implicitWidth + 14
    height: 20
    radius: Theme.rSm
    color: tone === "accent" ? Theme.accent : Theme.surface
    border.width: tone === "accent" ? 0 : 1
    border.color: tone === "bad" ? Theme.bad : tone === "warn" ? Theme.warn : Theme.line2
    LcText {
        id: label
        anchors.centerIn: parent
        text: root.text
        font.pixelSize: Theme.fsXs
        font.weight: Font.Medium
        tnum: true
        color: root.tone === "accent" ? Theme.accentInk : root.tone === "bad" ? Theme.bad : root.tone === "warn" ? Theme.warn : Theme.text
    }
}
