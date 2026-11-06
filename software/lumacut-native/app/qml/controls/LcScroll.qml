import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LumaCut

// Scrolling page: children stack in a ColumnLayout, centered up to maxContentWidth. The wheel moves in crisp steps.
Item {
    id: root
    property int padding: Theme.sp4
    property int maxContentWidth: 100000
    property alias spacing: col.spacing
    property alias contentY: flick.contentY
    default property alias content: col.data
    clip: true
    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: col.implicitHeight + 2 * root.padding
        contentWidth: width
        interactive: false
        boundsBehavior: Flickable.StopAtBounds
        ColumnLayout {
            id: col
            width: Math.min(root.maxContentWidth, flick.width - 2 * root.padding)
            x: (flick.width - width) / 2
            y: root.padding
            spacing: Theme.sp4
        }
        ScrollBar.vertical: LcScrollBar {}
    }
    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: (e) => { flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, flick.contentY - e.angleDelta.y / 120 * 64)) }
    }
}
