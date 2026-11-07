import QtQuick
import QtQuick.Layouts
import LumaCut

// Left panel of Platine: the files with their recognised layer, the board in numbers, what the preview shows.
Rectangle {
    id: root
    color: Theme.surface
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }

    LcMenu { id: kindMenu; objectName: "pcb-kind-menu"; property int file: -1 }

    LcScroll {
        anchors.fill: parent
        anchors.rightMargin: 1
        spacing: Theme.sp4

        // ---- Files ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.sp2
            RowLayout {
                Layout.fillWidth: true
                LcText { text: "Dateien"; kind: "section"; Layout.fillWidth: true }
                LcButton { objectName: "pcb-add"; size: "sm"; icon: "plus"; tip: "Weitere Dateien"; onClicked: Platine.askFiles() }
                LcButton {
                    objectName: "pcb-clear"; size: "sm"; variant: "ghost"; icon: "trash-2"; tip: "Alle entfernen"
                    onClicked: Confirm.ask({ title: "Alle Dateien entfernen?", body: "Die Platine verschwindet aus dieser Ansicht. Was schon im Projekt liegt, bleibt.", okLabel: "Entfernen" },
                                           function(yes) { if (yes) Platine.clear() })
                }
            }
            Repeater {
                model: Platine.files
                ColumnLayout {
                    id: fileRow
                    required property var modelData
                    required property int index
                    objectName: "pcb-file-" + index
                    Layout.fillWidth: true
                    spacing: 3
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.sp1
                        LcText { text: fileRow.modelData.name; elide: Text.ElideMiddle; Layout.fillWidth: true; font.weight: Font.Medium }
                        LcButton {
                            size: "sm"; variant: "ghost"; icon: "x"; tip: "Datei entfernen"
                            onClicked: Platine.removeFile(fileRow.index)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.sp2
                        LcChip {
                            id: chip
                            objectName: "pcb-kind-" + fileRow.index
                            text: fileRow.modelData.label
                            tone: fileRow.modelData.kind === "other" ? "" : "accent"
                            clickable: true
                            tip: "Lage ändern"
                            onClicked: {
                                const items = []
                                for (const k of Platine.kinds) items.push({ label: k.label, action: function() { Platine.setKind(fileRow.index, k.key) } })
                                kindMenu.items = items
                                kindMenu.openAt(chip)
                            }
                        }
                        LcText {
                            text: fileRow.modelData.summary
                            kind: "smallFaint"; tnum: true
                            color: fileRow.modelData.error.length > 0 ? Theme.bad : Theme.faint
                            elide: Text.ElideRight; Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }

        // ---- Board ----
        ColumnLayout {
            objectName: "pcb-facts"
            Layout.fillWidth: true
            spacing: Theme.sp2
            visible: Platine.hasBoard
            LcText { text: "Erkannte Platine"; kind: "section" }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.sp3
                rowSpacing: Theme.sp2
                LcStat { label: "Größe"; value: Platine.boardInfo.size || ""; valueName: "pcb-size"; Layout.columnSpan: 2 }
                LcStat { label: "Kupfer"; value: Platine.boardInfo.copper || ""; mono: false }
                LcStat { label: "Bohrungen"; value: Platine.boardInfo.drills || ""; valueName: "pcb-drills" }
                LcStat { label: "Lötstopp"; value: Platine.boardInfo.mask || ""; mono: false }
                LcStat { label: "Bestückungsdruck"; value: Platine.boardInfo.silk || ""; mono: false }
                LcStat { label: "Umriss"; value: Platine.boardInfo.outline || ""; mono: false }
            }
        }
        LcText {
            visible: !Platine.hasBoard && !Platine.busy
            text: "Noch keine Lage erkannt. Auf die Lage einer Datei klicken und sie zuordnen."
            kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line; visible: Platine.hasBoard }

        // ---- What the preview shows ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.sp2
            visible: Platine.viewLayers.length > 0
            LcText { text: "Ansicht"; kind: "section" }
            Repeater {
                model: Platine.viewLayers
                RowLayout {
                    id: vrow
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcCheck {
                        objectName: "pcb-layer-" + vrow.modelData.key
                        text: vrow.modelData.label
                        checked: vrow.modelData.shown
                        onToggled: Platine.toggleLayer(vrow.modelData.key)
                        Layout.fillWidth: true
                    }
                    Rectangle {
                        width: 12; height: 12; radius: 3
                        color: ({ copper: Theme.pcbCopper, laser: Theme.pcbLaser, drill: Theme.pcbDrill, mark: Theme.pcbMark,
                                  mask: Theme.pcbMask, silk: Theme.pcbSilk, edge: Theme.pcbEdge })[vrow.modelData.color] || Theme.faint
                        border.width: 1; border.color: Theme.line2
                    }
                }
            }
        }

        // ---- Warnings from the files ----
        Repeater {
            model: Platine.warnings
            LcNote { required property var modelData; tone: "warn"; text: modelData; Layout.fillWidth: true }
        }
    }
}
