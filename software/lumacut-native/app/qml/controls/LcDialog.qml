import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import LumaCut

// Modal dialog, below the top bar so NOT-AUS stays reachable. Declare it anywhere; it lifts itself into Shell.overlay.
//   open, title, dialogWidth, locked (no Esc, no click away), initialFocus (item), footer: [ LcButton {...} ].
//   Children stack in a ColumnLayout. rejected() fires on Esc and click away; set open = false there.
Item {
    id: root
    property bool open: false
    property string title
    property int dialogWidth: 480
    property bool locked: false
    property Item initialFocus: null
    default property alias content: body.data
    property alias footer: foot.data
    property alias footerLeft: footLeft.data
    property alias bodySpacing: body.spacing
    signal rejected()
    function requestClose() { if (!locked) rejected() }

    parent: Shell.overlay
    anchors.fill: parent
    visible: open
    z: 100
    onOpenChanged: {
        if (open) {
            Shell.pushModal(root)
            focusTimer.start()
        } else {
            Shell.popModal(root)
        }
    }
    Component.onCompleted: if (open) { Shell.pushModal(root); focusTimer.start() }
    Component.onDestruction: Shell.popModal(root)
    Timer {
        id: focusTimer
        interval: 0
        onTriggered: (root.initialFocus || panel).forceActiveFocus(Qt.TabFocusReason)
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        opacity: root.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.tMed } }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.AllButtons
            onPressed: if (!root.locked) root.rejected()
            onWheel: (w) => w.accepted = true
        }
    }
    RectangularShadow {
        anchors.fill: panel
        offset.y: 14
        blur: 44
        radius: panel.radius
        color: Theme.shadowStrong
        opacity: panel.opacity
    }
    Rectangle {
        id: panel
        objectName: root.objectName.length ? root.objectName + "-panel" : ""
        anchors.centerIn: parent
        width: Math.min(root.dialogWidth, root.width - 2 * Theme.sp5)
        height: Math.min(layout.implicitHeight, root.height - 2 * Theme.sp5)
        radius: Theme.rXl
        color: Theme.surface
        scale: root.open ? 1 : .985
        Behavior on scale { NumberAnimation { duration: Theme.tMed; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (w) => w.accepted = true }
        ColumnLayout {
            id: layout
            anchors.fill: parent
            spacing: 0
            LcText {
                text: root.title
                kind: "h2"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Layout.leftMargin: Theme.sp5; Layout.rightMargin: Theme.sp5
                Layout.topMargin: Theme.sp4; Layout.bottomMargin: Theme.sp2
            }
            Flickable {
                id: scroller
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: body.implicitHeight + Theme.sp2 + Theme.sp4
                contentHeight: Layout.preferredHeight
                clip: contentHeight > height
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds
                ColumnLayout {
                    id: body
                    x: Theme.sp5; y: Theme.sp2
                    width: scroller.width - 2 * Theme.sp5
                    spacing: Theme.sp3
                }
            }
            Item {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.sp5; Layout.rightMargin: Theme.sp5
                Layout.bottomMargin: Theme.sp4; Layout.topMargin: Theme.sp1
                implicitHeight: Math.max(foot.implicitHeight, footLeft.implicitHeight)
                Row { id: footLeft; spacing: Theme.sp2 }
                Row { id: foot; spacing: Theme.sp2; anchors.right: parent.right }
            }
        }
    }
}
