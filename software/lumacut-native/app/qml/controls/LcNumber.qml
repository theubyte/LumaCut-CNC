import QtQuick
import LumaCut

// Number field. Enter or leaving the field takes the value, Esc restores it, Up/Down change it by step (Shift x10).
// Comma and point are read, the comma is shown. The typed text is never fought while focused.
// value is yours: react to edited(v). Exact values stay untouched unless someone types.
Rectangle {
    id: root
    property real value: 0
    property real min: -Infinity
    property real max: Infinity
    property real step: 1
    property int digits: 2
    property string unit
    property string tip
    signal edited(real v)

    function _fmt(v) { return Fmt.trim(v, digits) }
    function _clamp(v) { return Math.min(max, Math.max(min, v)) }
    function _commit() {
        if (input.text === _fmt(value)) return
        const v = Fmt.parse(input.text)
        if (isNaN(v)) { input.text = _fmt(value); return }
        const c = _clamp(v)
        input.text = _fmt(c)
        if (c !== value) edited(c)
    }
    function _stepBy(dir, shift) {
        const cur = Fmt.parse(input.text)
        const c = _clamp((isNaN(cur) ? value : cur) + dir * step * (shift ? 10 : 1))
        input.text = _fmt(c)
        edited(c)
    }
    onValueChanged: if (!input.activeFocus) input.text = _fmt(value)
    onDigitsChanged: if (!input.activeFocus) input.text = _fmt(value)
    Component.onCompleted: input.text = _fmt(value)

    implicitWidth: 84
    implicitHeight: Theme.hControl
    radius: Theme.rMd
    color: Theme.surface
    border.width: 1
    border.color: input.activeFocus ? Theme.accent : hover.hovered ? Theme.faint : Theme.line2
    opacity: enabled ? 1 : .55
    HoverHandler { id: hover; cursorShape: Qt.IBeamCursor }
    Rectangle { anchors.fill: parent; anchors.margins: -3; radius: root.radius + 3; color: "transparent"; border.width: 3; border.color: Theme.accentSoft; visible: input.activeFocus }
    LcText { id: unitText; text: root.unit; visible: root.unit.length > 0; kind: "smallFaint"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }
    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: root.unit.length > 0 ? unitText.width + 14 : 8
        objectName: root.objectName.length ? root.objectName + "-input" : ""
        horizontalAlignment: TextInput.AlignRight
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.text
        selectionColor: Theme.accent
        selectedTextColor: Theme.accentInk
        selectByMouse: true
        activeFocusOnTab: true
        clip: true
        renderType: TextInput.NativeRendering
        font.family: Theme.font
        font.pixelSize: Theme.fsMd
        font.features: ({ "tnum": 1 })
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        onActiveFocusChanged: { if (activeFocus) selectAll(); else root._commit() }
        Keys.onPressed: (e) => {
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { root._commit(); input.focus = false; e.accepted = true }
            else if (e.key === Qt.Key_Escape && !Shell.modalOpen) { input.text = root._fmt(root.value); input.focus = false; e.accepted = true }
            else if (e.key === Qt.Key_Up || e.key === Qt.Key_Down) { root._stepBy(e.key === Qt.Key_Up ? 1 : -1, e.modifiers & Qt.ShiftModifier); e.accepted = true }
        }
    }
    LcTip { shown: hover.hovered; text: root.tip }
}
