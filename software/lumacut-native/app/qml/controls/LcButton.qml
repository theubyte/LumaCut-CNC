import QtQuick
import LumaCut

// variant: default, primary, ghost, danger. size: sm, md, lg. icon: Lucide name. No text = square icon button.
// lock: sentence why it is locked (dims it, refuses the click, is the tooltip). busy: spinner, refuses the click.
// keyActivation false: Enter and Space do nothing (the go dialog's start button).
Item {
    id: root
    property string text
    property string icon
    property string variant: "default"
    property string size: "md"
    property string lock
    property string tip
    property bool busy: false
    property bool pressedLook: false
    property bool keyActivation: true
    property color textColor: variant === "primary" ? Theme.accentInk : variant === "danger" ? "white" : Theme.text
    readonly property bool active: enabled && !lock && !busy
    signal clicked()

    readonly property int _h: size === "sm" ? Theme.hControlSm : size === "lg" ? Theme.hControlLg : Theme.hControl
    readonly property int _pad: size === "sm" ? 7 : size === "lg" ? 16 : 11
    readonly property int _icon: size === "sm" ? 14 : size === "lg" ? 16 : 15
    readonly property bool _iconOnly: !text.length && !busy
    implicitHeight: _h
    implicitWidth: _iconOnly ? _h : row.implicitWidth + 2 * _pad
    activeFocusOnTab: true
    opacity: active || busy ? 1 : .45
    Behavior on opacity { NumberAnimation { duration: Theme.tFast } }

    function _click() { if (active) clicked() }
    Keys.onPressed: (e) => {
        if (keyActivation && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) && !e.isAutoRepeat) { _click(); e.accepted = true }
    }

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: root.size === "lg" ? Theme.rLg : root.size === "sm" ? Theme.rSm : Theme.rMd
        readonly property bool hot: area.containsMouse && root.active
        color: root.pressedLook ? Theme.accentSoft
             : root.variant === "primary" ? (hot ? Theme.accentHover : Theme.accent)
             : root.variant === "danger" ? (hot ? Qt.lighter(Theme.bad, 1.08) : Theme.bad)
             : root.variant === "ghost" ? (hot ? Theme.surface3 : "transparent")
             : (hot ? Theme.surface3 : Theme.surface)
        border.width: 1
        border.color: root.pressedLook || root.variant === "ghost" ? "transparent"
                    : root.variant === "primary" ? color : root.variant === "danger" ? color : Theme.line2
        Behavior on color { ColorAnimation { duration: Theme.tFast } }
    }
    Rectangle {
        anchors.fill: parent; anchors.margins: -2
        radius: bg.radius + 2; color: "transparent"
        border.width: 2; border.color: Theme.accent
        visible: root.activeFocus
    }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        LcIcon {
            visible: root.icon.length > 0
            name: root.icon; size: root._icon; width: size; height: size
            color: root.pressedLook ? Theme.accent : root.textColor
            anchors.verticalCenter: parent.verticalCenter
        }
        LcText {
            visible: root.text.length > 0
            text: root.text
            color: root.pressedLook ? Theme.accent : root.textColor
            font.pixelSize: root.size === "lg" ? Theme.fsLg : root.size === "sm" ? Theme.fsSm : Theme.fsMd
            font.weight: root.variant === "primary" || root.variant === "danger" ? Font.DemiBold : Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
        LcSpinner { visible: root.busy; size: 12; color: root.textColor; anchors.verticalCenter: parent.verticalCenter }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.active ? Qt.PointingHandCursor : Qt.ForbiddenCursor
        onClicked: root._click()
    }
    LcTip { shown: area.containsMouse; text: root.lock || root.tip }
}
