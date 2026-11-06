import QtQuick

Item {
    property string title
    Text { x: Theme.sp6; y: Theme.sp5; text: parent.title; color: Theme.text; font.family: Theme.fontDisplay; font.pixelSize: Theme.fs2xl; font.weight: Font.DemiBold }
}
