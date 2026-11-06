import QtQuick
import LumaCut

Item {
    objectName: "view-Start"
    GpuProbe { anchors.fill: parent }
    Text { x: Theme.sp6; y: Theme.sp5; text: "Start"; color: Theme.text; font.family: Theme.fontDisplay; font.pixelSize: Theme.fs2xl; font.weight: Font.DemiBold }
}
