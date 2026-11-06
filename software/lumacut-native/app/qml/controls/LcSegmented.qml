import QtQuick
import LumaCut

// options: [{ value, label, icon?, tip? }]. value is yours: react to activated(v). Parts are named <objectName>-<value>.
Rectangle {
    id: root
    property var options: []
    property var value
    signal activated(var v)
    radius: Theme.rMd
    color: Theme.surface3
    implicitHeight: Theme.hControl
    // From the parts' natural widths, never their stretched ones: a stretched control must not feed back into layout.
    readonly property real naturalWidth: {
        let w = 4 + 2 * Math.max(0, parts.count - 1);
        for (let i = 0; i < parts.count; ++i) { const p = parts.itemAt(i); if (p) w += p.natural; }
        return w;
    }
    implicitWidth: naturalWidth
    opacity: enabled ? 1 : .5
    Row {
        id: row
        x: 2; y: 2
        height: parent.height - 4
        spacing: 2
        Repeater {
            id: parts
            model: root.options
            Rectangle {
                id: seg
                required property var modelData
                required property int index
                readonly property bool on: root.value === modelData.value
                objectName: root.objectName.length ? root.objectName + "-" + modelData.value : ""
                height: row.height
                readonly property real natural: segRow.implicitWidth + 20
                width: Math.max(natural, root.width > root.naturalWidth ? (root.width - 4 - 2 * (root.options.length - 1)) / root.options.length : 0)
                radius: Theme.rSm
                color: on ? Theme.surface : "transparent"
                activeFocusOnTab: true
                border.width: activeFocus ? 2 : 0
                border.color: Theme.accent
                Keys.onPressed: (e) => { if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) { root.activated(modelData.value); e.accepted = true } }
                Row {
                    id: segRow
                    anchors.centerIn: parent
                    spacing: 5
                    LcIcon { visible: !!seg.modelData.icon; name: seg.modelData.icon || ""; size: 14; width: 14; height: 14; color: label.color; anchors.verticalCenter: parent.verticalCenter }
                    LcText { id: label; text: seg.modelData.label; font.weight: seg.on ? Font.DemiBold : Font.Medium; color: seg.on || area.containsMouse ? Theme.text : Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.activated(seg.modelData.value) }
                LcTip { shown: area.containsMouse; text: seg.modelData.tip || "" }
            }
        }
    }
}
