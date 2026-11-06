import QtQuick
import QtQuick.Layouts
import LumaCut

// The column of drawing tools with their keys.
Rectangle {
    id: root
    color: Theme.surface
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
    readonly property var tools: [
        { key: "select", label: "Auswählen", icon: "mouse-pointer-2", kbd: "V" },
        { key: "node", label: "Knoten bearbeiten", icon: "spline", kbd: "A" },
        { key: "rect", label: "Rechteck", icon: "rectangle-horizontal", kbd: "R", gap: true },
        { key: "ellipse", label: "Ellipse", icon: "circle", kbd: "E" },
        { key: "poly", label: "Linie und Polygon", icon: "pen-line", kbd: "L" },
        { key: "pen", label: "Stift mit Kurven", icon: "pen-tool", kbd: "P" },
        { key: "text", label: "Text", icon: "type", kbd: "T", gap: true },
        { key: "image", label: "Bild einfügen", icon: "image-plus", kbd: "I" },
        { key: "measure", label: "Messen", icon: "ruler", kbd: "M", gap: true }
    ]
    Column {
        x: (parent.width - 1 - width) / 2
        y: Theme.sp2
        spacing: 2
        Repeater {
            model: root.tools
            Column {
                id: entry
                required property var modelData
                spacing: 0
                Item {
                    visible: !!entry.modelData.gap
                    width: 34; height: Theme.sp4 + 1
                    Rectangle { anchors.centerIn: parent; width: parent.width - 8; height: 1; color: Theme.line }
                }
                Rectangle {
                    id: button
                    objectName: "tool-" + entry.modelData.key
                    readonly property bool on: Editor.tool === entry.modelData.key
                    width: 34; height: 34
                    radius: Theme.rMd
                    color: on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
                    LcIcon {
                        anchors.centerIn: parent
                        name: entry.modelData.icon
                        size: 17; width: 17; height: 17; strokeWidth: 1.8
                        color: button.on ? Theme.accent : area.containsMouse ? Theme.text : Theme.muted
                    }
                    LcText {
                        anchors.right: parent.right; anchors.bottom: parent.bottom
                        anchors.rightMargin: 3; anchors.bottomMargin: 1
                        text: entry.modelData.kbd
                        color: button.on ? Theme.accent : Theme.faint
                        font.pixelSize: Theme.fsXs - 2
                        font.weight: Font.Medium
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (entry.modelData.key === "image") { Editor.tool = "select"; Editor.askImport(true) }
                            else Editor.tool = entry.modelData.key
                        }
                    }
                    LcTip { shown: area.containsMouse; side: "right"; text: entry.modelData.label + " (" + entry.modelData.kbd + ")" }
                }
            }
        }
    }
}
