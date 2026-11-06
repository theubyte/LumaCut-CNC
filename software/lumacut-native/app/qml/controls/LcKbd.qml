import QtQuick
import LumaCut

// A key cap in running text.
Rectangle {
    property string text
    radius: 4
    color: Theme.surface3
    implicitWidth: label.implicitWidth + 10
    implicitHeight: label.implicitHeight + 3
    LcText { id: label; anchors.centerIn: parent; text: parent.text; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.fsXs; font.weight: Font.Medium }
}
