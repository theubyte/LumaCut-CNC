import QtQuick
import QtQuick.Controls
import LumaCut

// Tooltip after a short delay: LcTip { shown: area.containsMouse; text: "..." }. Built only when needed.
Loader {
    id: tip
    property string text
    property bool shown: false
    property string side: "top"   // top or right
    active: shown && text.length > 0
    sourceComponent: ToolTip {
        parent: tip.parent
        visible: true
        delay: 450
        timeout: 6000
        margins: Theme.sp2
        x: tip.side === "right" ? parent.width + 6 : (parent.width - width) / 2
        y: tip.side === "right" ? (parent.height - height) / 2 : -height - 4
        padding: 0
        contentItem: LcText { text: tip.text; kind: "small"; wrapMode: Text.WordWrap; width: Math.min(implicitWidth, 320); leftPadding: 8; rightPadding: 8; topPadding: 5; bottomPadding: 5 }
        background: Rectangle { color: Theme.surface; border.color: Theme.line2; radius: Theme.rMd }
        enter: null
        exit: null
    }
}
