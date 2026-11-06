import QtQuick
import QtQuick.Layouts
import LumaCut

// Plates, then what is selected and where the mouse is.
Rectangle {
    id: root
    objectName: "plate-bar"
    color: Theme.surface
    Rectangle { width: parent.width; height: 1; color: Theme.line }
    readonly property var sel: Editor.sel
    property int menuPlate: 0

    function askDelete(i) {
        const n = Editor.plateCounts[i] || 0
        if (n === 0) { Editor.deletePlate(i); return }
        Confirm.ask({ title: "Platte " + (i + 1) + " entfernen?", body: n + (n === 1 ? " Objekt wird" : " Objekte werden") + " mitgelöscht. Rückgängig holt alles zurück.", okLabel: "Entfernen", danger: true },
                    (yes) => { if (yes) Editor.deletePlate(i) })
    }
    LcMenu {
        id: plateMenu
        objectName: "plate-menu"
        items: [{ label: "Platte " + (root.menuPlate + 1) + " entfernen", disabled: Document.plateCount <= 1, action: () => root.askDelete(root.menuPlate) }]
    }
    LcMenu { id: moveMenu; objectName: "plate-move-list" }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.sp3
        anchors.rightMargin: Theme.sp3
        anchors.topMargin: 1
        spacing: Theme.sp1
        Row {
            spacing: 2
            Repeater {
                model: Document.plateCount
                Rectangle {
                    id: tab
                    required property int index
                    objectName: "plate-" + index
                    readonly property bool on: Document.activePlate === index
                    width: tabText.implicitWidth + 16
                    height: Theme.hControlSm
                    radius: Theme.rSm
                    color: on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
                    LcText {
                        id: tabText
                        anchors.centerIn: parent
                        text: "Platte " + (tab.index + 1)
                        kind: "small"
                        color: tab.on ? Theme.accent : Theme.muted
                        font.weight: tab.on ? Font.DemiBold : Font.Medium
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: (m) => {
                            if (m.button === Qt.RightButton) {
                                root.menuPlate = tab.index
                                const p = tab.mapToItem(null, m.x, m.y)
                                plateMenu.popup(p.x, p.y)
                            } else Editor.setPlate(tab.index)
                        }
                    }
                    LcTip { shown: area.containsMouse; text: "Platte " + (tab.index + 1) + ": " + (Editor.plateCounts[tab.index] || 0) + " Objekte (Bild auf, Bild ab). Rechtsklick: entfernen." }
                }
            }
        }
        LcButton { objectName: "plate-add"; variant: "ghost"; size: "sm"; icon: "plus"; tip: "Platte hinzufügen"; onClicked: Editor.addPlate() }
        LcButton {
            id: moveBtn
            objectName: "plate-move"
            visible: (root.sel.count || 0) > 0
            variant: "ghost"
            size: "sm"
            text: "Auswahl verschieben auf"
            onClicked: {
                const list = []
                for (let i = 0; i < Document.plateCount; i++) {
                    const k = i
                    list.push({ label: "Platte " + (i + 1), disabled: i === Document.activePlate, action: () => Editor.moveSelectionToPlate(k) })
                }
                list.push({ separator: true }, { label: "Neue Platte", action: () => Editor.moveSelectionToPlate(Document.plateCount) })
                moveMenu.items = list
                const p = moveBtn.mapToItem(null, 0, -(list.length * 30 + 12))
                moveMenu.popup(p.x, p.y)
            }
        }
        Item { Layout.fillWidth: true }
        LcText {
            objectName: "sel-info"
            visible: (root.sel.count || 0) > 0
            kind: "mono"
            color: Theme.muted
            font.pixelSize: Theme.fsSm
            text: (root.sel.count === 1 ? "1 Objekt" : root.sel.count + " Objekte")
                  + (root.sel.hasBox ? " · " + Fmt.trim(root.sel.boxW, 1) + " × " + Fmt.trim(root.sel.boxH, 1) + " mm" : "")
        }
        LcText {
            objectName: "mouse-pos"
            Layout.minimumWidth: 150
            Layout.leftMargin: Theme.sp2
            horizontalAlignment: Text.AlignRight
            kind: "mono"
            color: Theme.muted
            font.pixelSize: Theme.fsSm
            text: Editor.mouseText
        }
    }
}
