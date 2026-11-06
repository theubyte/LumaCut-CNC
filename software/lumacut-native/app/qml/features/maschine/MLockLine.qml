import QtQuick
import QtQuick.Layouts
import LumaCut

// Why something is locked, with the next step. Invisible when free.
RowLayout {
    property string text
    objectName: "lock-line"
    visible: text.length > 0
    spacing: 6
    Layout.fillWidth: true
    LcIcon { name: "lock"; size: 13; width: 13; height: 13; color: Theme.warn; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2; Layout.preferredWidth: 13; Layout.preferredHeight: 13 }
    LcText { text: parent.text; kind: "small"; color: Theme.warn; wrapMode: Text.WordWrap; Layout.fillWidth: true }
}
