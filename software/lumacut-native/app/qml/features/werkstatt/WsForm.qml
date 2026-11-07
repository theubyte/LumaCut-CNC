import QtQuick
import QtQuick.Layouts
import LumaCut

// The form of the open generator, built from Workshop.fields: rows, section titles, hints and simple fields.
ColumnLayout {
    id: root
    spacing: Theme.sp3
    Repeater {
        model: Workshop.fields
        Item {
            id: entry
            required property var modelData
            Layout.fillWidth: true
            Layout.topMargin: modelData.type === "section" ? Theme.sp1 : 0
            implicitHeight: body.item ? body.item.implicitHeight : 0
            Loader {
                id: body
                width: entry.width
                sourceComponent: entry.modelData.type === "row" ? rowC : entry.modelData.type === "section" ? sectionC
                               : entry.modelData.type === "note" ? noteC : fieldC
            }
            Component {
                id: rowC
                RowLayout {
                    spacing: Theme.sp2
                    Repeater {
                        model: entry.modelData.fields
                        WsField {
                            required property var modelData
                            field: modelData
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                        }
                    }
                }
            }
            Component { id: sectionC; LcText { text: entry.modelData.label; kind: "section" } }
            Component { id: noteC; LcNote { text: entry.modelData.text; tone: entry.modelData.tone } }
            Component { id: fieldC; WsField { field: entry.modelData } }
        }
    }
}
