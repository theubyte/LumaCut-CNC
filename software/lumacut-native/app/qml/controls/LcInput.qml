import QtQuick
import LumaCut

// Text field. text, placeholder, icon (Lucide, left), mono, maxLength. Signals: edited(text) on each change by the user, accepted on Enter.
Rectangle {
    id: root
    property alias text: input.text
    property string placeholder
    property string icon
    property bool mono: false
    property alias maxLength: input.maximumLength
    property alias input: input
    signal edited(string text)
    signal accepted()
    function selectAll() { input.selectAll() }
    function focusNow() { input.forceActiveFocus(); input.selectAll() }

    implicitWidth: 160
    implicitHeight: Theme.hControl
    radius: Theme.rMd
    color: Theme.surface
    border.width: 1
    border.color: input.activeFocus ? Theme.accent : hover.hovered ? Theme.faint : Theme.line2
    opacity: enabled ? 1 : .55
    HoverHandler { id: hover; cursorShape: Qt.IBeamCursor }
    Rectangle { anchors.fill: parent; anchors.margins: -3; radius: root.radius + 3; color: "transparent"; border.width: 3; border.color: Theme.accentSoft; visible: input.activeFocus }
    LcIcon { id: ic; visible: root.icon.length > 0; name: root.icon; size: 14; width: 14; height: 14; color: Theme.faint; x: 8; anchors.verticalCenter: parent.verticalCenter }
    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: root.icon.length > 0 ? 27 : 8
        anchors.rightMargin: 8
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.text
        selectionColor: Theme.accent
        selectedTextColor: Theme.accentInk
        selectByMouse: true
        clip: true
        activeFocusOnTab: true
        renderType: TextInput.NativeRendering
        font.family: root.mono ? Theme.mono : Theme.font
        font.pixelSize: Theme.fsMd
        onTextEdited: root.edited(text)
        onAccepted: root.accepted()
    }
    LcText {
        visible: !input.text.length && root.placeholder.length > 0
        text: root.placeholder
        kind: "faint"
        anchors.fill: input
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
