import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import LumaCut

// Small movable window with the head-camera picture, over the motif stage. Shown while Scanner.liveOn.
Item {
    id: root
    objectName: "live-window-box"
    visible: Scanner.liveOn
    width: 320
    height: 40 + width * 3 / 4
    x: parent ? parent.width - width - Theme.sp4 : 0
    y: Theme.sp5 + Theme.sp5
    z: 40
    RectangularShadow { anchors.fill: box; offset.y: 4; blur: 14; radius: box.radius; color: Theme.shadowSoft }
    Rectangle {
        id: box
        anchors.fill: parent
        radius: Theme.rLg
        color: Theme.surface
        border.width: 1
        border.color: Theme.line
        clip: true
        Item {
            id: head
            width: parent.width
            height: 34
            MouseArea { anchors.fill: parent; cursorShape: Qt.SizeAllCursor; drag.target: root; drag.threshold: 2 }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.sp3
                anchors.rightMargin: Theme.sp1
                spacing: Theme.sp2
                LcIcon { name: "camera"; size: 14; width: 14; height: 14; color: Theme.muted }
                LcText { text: "Kopfkamera"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                LcText { objectName: "live-count"; text: Scanner.liveFrames + " Bilder"; kind: "smallFaint"; tnum: true }
                LcButton { objectName: "live-close"; icon: "x"; variant: "ghost"; size: "sm"; tip: "Schließen"; onClicked: Scanner.liveOn = false }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
        }
        Rectangle {
            x: 1; y: head.height
            width: parent.width - 2
            height: parent.height - head.height - 1
            color: Theme.canvas
            ScanImage { id: img; objectName: "live-image"; anchors.fill: parent; source: "live" }
            LcText {
                visible: !img.hasImage || Scanner.liveError.length > 0
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.sp4
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                kind: "muted"
                text: Scanner.liveError.length ? Scanner.liveError : "Bild wird geholt …"
            }
            MvPill {
                visible: Scanner.liveNote.length > 0
                anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: Theme.sp2
                text: Scanner.liveNote
                tone: "warn"
            }
        }
    }
}
