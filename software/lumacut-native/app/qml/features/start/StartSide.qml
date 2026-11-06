import QtQuick
import QtQuick.Layouts
import LumaCut

// The right side: material, numbers, layers, checks, or the running job; below them Rahmen and Starten.
Rectangle {
    id: root
    objectName: "start-side"
    color: Theme.surface
    // Columns of the layer table, wide enough for their heads at the smallest window.
    readonly property int colPower: 46
    readonly property int colSpeed: 36
    readonly property int colPasses: 40
    readonly property int colInterval: 44
    Rectangle { width: 1; height: parent.height; color: Theme.line }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0

        LcScroll {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp4

            // Result of the last run, with the Pi's sentence.
            Rectangle {
                objectName: "start-result"
                visible: Start.resultShown
                Layout.fillWidth: true
                implicitHeight: resultText.implicitHeight + Theme.sp3 * 2
                radius: Theme.rMd
                readonly property string tone: Start.resultTone
                color: tone === "ok" ? Theme.okSoft : tone === "bad" ? Theme.badSoft : Theme.infoSoft
                LcIcon {
                    x: Theme.sp3; y: Theme.sp3
                    width: 15; height: 15; size: 15
                    name: parent.tone === "ok" ? "check-circle-2" : parent.tone === "bad" ? "x-circle" : "info"
                    color: parent.tone === "ok" ? Theme.ok : parent.tone === "bad" ? Theme.bad : Theme.info
                }
                LcText {
                    id: resultText
                    objectName: "start-result-text"
                    x: Theme.sp3 + 15 + Theme.sp2; y: Theme.sp3
                    width: parent.width - x - Theme.sp3 - Theme.hControlSm
                    text: Start.resultText
                    wrapMode: Text.WordWrap
                }
                LcButton {
                    objectName: "start-result-close"
                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Theme.sp1
                    icon: "x"; size: "sm"; variant: "ghost"; tip: "Meldung schließen"
                    onClicked: Start.dismissResult()
                }
            }

            // ---- Before the run ----
            ColumnLayout {
                visible: !Start.running
                Layout.fillWidth: true
                spacing: Theme.sp4

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp3
                    RowLayout {
                        visible: Start.isSaved
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 2
                            Layout.fillWidth: true
                            LcText { text: "Gespeicherter Auftrag"; kind: "smallFaint" }
                            LcText { objectName: "start-source-name"; text: Start.name; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideMiddle }
                        }
                        LcButton { objectName: "start-back-to-motif"; text: "Zum Motiv"; icon: "arrow-left"; size: "sm"; variant: "ghost"; onClicked: Start.backToDoc() }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 2
                            Layout.fillWidth: true
                            LcText { text: "Material"; kind: "smallFaint" }
                            LcText { objectName: "start-material"; text: Start.materialText; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideRight }
                        }
                        LcButton { objectName: "start-material-go"; text: Start.materialChosen ? "Ändern" : "Wählen"; size: "sm"; onClicked: Shell.navigate("material") }
                    }
                    ColumnLayout {
                        visible: Start.multi && !Start.isSaved
                        spacing: Theme.sp1
                        Layout.fillWidth: true
                        LcText { text: "Platte"; kind: "smallFaint" }
                        LcSegmented {
                            objectName: "start-plate"
                            options: Start.plateOptions
                            value: Start.plate
                            onActivated: (v) => Start.choosePlate(v)
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    LcText { text: "Zeitschätzung"; kind: "smallFaint" }
                    LcText {
                        objectName: "start-estimate"
                        text: Start.estimate
                        font.family: Theme.fontDisplay
                        font.pixelSize: Theme.fs3xl
                        font.weight: Font.DemiBold
                        tnum: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.sp2
                        spacing: Theme.sp3
                        Repeater {
                            model: [["Laserweg", Start.cutLength, "start-cut", 100], ["Leerweg", Start.travelLength, "start-travel-length", 100], ["Größe", Start.sizeText, "start-size", 140]]
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredWidth: modelData[3]
                                spacing: 2
                                LcText { text: modelData[0]; kind: "smallFaint" }
                                LcText { objectName: modelData[2]; text: modelData[1]; font.weight: Font.Medium; tnum: true; Layout.fillWidth: true; elide: Text.ElideRight }
                            }
                        }
                    }
                }

                ColumnLayout {
                    visible: Start.layerRows.length > 0
                    Layout.fillWidth: true
                    spacing: Theme.sp1
                    LcText { text: "Ebenen"; kind: "section" }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.sp1
                        spacing: Theme.sp1
                        Item { Layout.fillWidth: true }
                        Repeater {
                            model: [["Leistung", root.colPower], ["Tempo", root.colSpeed], ["Durchg.", root.colPasses], ["Abstand", root.colInterval]]
                            LcText { required property var modelData; text: modelData[0]; kind: "smallFaint"; font.pixelSize: Theme.fsXs; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: modelData[1] }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                    Repeater {
                        model: Start.layerRows
                        RowLayout {
                            required property var modelData
                            objectName: "start-layer-" + modelData.name
                            Layout.fillWidth: true
                            Layout.preferredHeight: Theme.hControlSm + Theme.sp1
                            spacing: Theme.sp1
                            opacity: modelData.on ? 1 : .55
                            Rectangle { width: 9; height: 9; radius: 5; color: modelData.color; opacity: parent.modelData.on ? 1 : .35; Layout.rightMargin: Theme.sp1 }
                            LcText { text: modelData.name; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideRight }
                            LcText { visible: modelData.on; text: modelData.power; kind: "small"; tnum: true; color: modelData.weak ? Theme.warn : Theme.text; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: root.colPower }
                            LcText { visible: modelData.on; text: modelData.speed; kind: "small"; tnum: true; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: root.colSpeed }
                            LcText { visible: modelData.on; text: modelData.passes; kind: "small"; tnum: true; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: root.colPasses }
                            LcText { visible: modelData.on; text: modelData.interval; kind: "small"; tnum: true; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: root.colInterval }
                            LcText { visible: !modelData.on; text: "aus"; kind: "smallMuted" }
                        }
                    }
                    LcText { text: "Tempo in mm/min, Abstand in mm"; kind: "smallFaint"; font.pixelSize: Theme.fsXs }
                }

                ColumnLayout {
                    objectName: "start-checks"
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcText { text: "Prüfungen"; kind: "section" }
                    RowLayout {
                        objectName: "check-ok"
                        visible: !Start.serious
                        Layout.fillWidth: true
                        spacing: Theme.sp2
                        LcIcon { name: "check-circle-2"; size: 15; width: 15; height: 15; color: Theme.ok; Layout.alignment: Qt.AlignTop }
                        LcText { text: "Alles in Ordnung, der Auftrag kann starten."; color: Theme.ok; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                    Repeater {
                        model: Start.checks
                        RowLayout {
                            required property var modelData
                            objectName: "check-" + modelData.id
                            Layout.fillWidth: true
                            spacing: Theme.sp2
                            readonly property string tone: modelData.tone
                            LcIcon {
                                name: parent.tone === "bad" ? "x-circle" : parent.tone === "warn" ? "alert-triangle" : "info"
                                size: 15; width: 15; height: 15
                                color: parent.tone === "bad" ? Theme.bad : parent.tone === "warn" ? Theme.warn : Theme.faint
                                Layout.alignment: Qt.AlignTop
                            }
                            LcText {
                                objectName: "check-text-" + parent.modelData.id
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                textFormat: Text.StyledText
                                linkColor: Theme.accent
                                color: parent.tone === "info" ? Theme.muted : Theme.text
                                text: parent.modelData.html
                                onLinkActivated: (dest) => Shell.navigate(dest)
                                HoverHandler { cursorShape: parent.hoveredLink.length ? Qt.PointingHandCursor : Qt.ArrowCursor }
                            }
                        }
                    }
                }
            }

            // ---- During the run ----
            ColumnLayout {
                objectName: "start-run"
                visible: Start.running
                Layout.fillWidth: true
                spacing: Theme.sp4
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    LcText { text: "Auftrag läuft"; kind: "smallFaint" }
                    LcText { objectName: "start-run-file"; text: Start.runFile; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideMiddle }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcText {
                        objectName: "start-run-percent"
                        text: Start.runPercent
                        font.family: Theme.fontDisplay
                        font.pixelSize: Theme.fs3xl
                        font.weight: Font.DemiBold
                        tnum: true
                    }
                    LcProgress { objectName: "start-run-progress"; Layout.fillWidth: true; value: Start.runShare }
                    LcText { objectName: "start-run-remaining"; text: Start.runRemaining; kind: "muted"; tnum: true }
                }
                ColumnLayout {
                    objectName: "start-phases"
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    Repeater {
                        model: Start.phases
                        RowLayout {
                            required property var modelData
                            objectName: "start-phase-" + modelData.number
                            property string state_: modelData.state
                            spacing: Theme.sp2
                            Layout.fillWidth: true
                            Rectangle {
                                width: 20; height: 20; radius: 10
                                color: parent.state_ === "done" ? Theme.okSoft : parent.state_ === "now" ? Theme.accent : Theme.surface3
                                LcIcon { anchors.centerIn: parent; visible: parent.parent.state_ === "done"; name: "check"; size: 12; width: 12; height: 12; strokeWidth: 3; color: Theme.ok }
                                LcIcon { anchors.centerIn: parent; visible: parent.parent.state_ === "now"; name: "play"; size: 10; width: 10; height: 10; color: Theme.accentInk }
                                LcText { anchors.centerIn: parent; visible: parent.parent.state_ === "next"; text: parent.parent.modelData.number; kind: "smallFaint"; font.pixelSize: Theme.fsXs }
                            }
                            LcText {
                                text: parent.modelData.label
                                color: parent.state_ === "next" ? Theme.faint : Theme.text
                                font.weight: parent.state_ === "now" ? Font.DemiBold : Font.Normal
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }

        // ---- Actions ----
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.sp4
            spacing: Theme.sp2
            LcButton {
                objectName: "frame-go"
                visible: !Start.running && !Start.framing
                Layout.fillWidth: true
                text: Start.busy === "frame" ? "Rahmen wird vorbereitet …" : "Rahmen"
                tip: "Der Kopf fährt den Umriss des Auftrags ab"
                lock: Start.busy === "frame" ? "" : Start.frameLock
                busy: Start.busy === "frame"
                onClicked: Start.frame()
            }
            LcButton {
                objectName: "frame-abort"
                visible: !Start.running && Start.framing
                Layout.fillWidth: true
                icon: "square"
                text: Start.frameText
                onClicked: Start.abort()
            }
            LcButton {
                objectName: "start-go"
                visible: !Start.running
                Layout.fillWidth: true
                variant: "danger"; size: "lg"; icon: "zap"
                text: Start.busy === "start" ? "Wird gesendet …" : "Starten"
                lock: Start.busy === "start" ? "" : Start.startLock
                busy: Start.busy === "start"
                onClicked: Start.startJob()
            }
            LcButton {
                objectName: "run-abort"
                visible: Start.running
                Layout.fillWidth: true
                size: "lg"; icon: "square"
                text: "Abbrechen"
                onClicked: Start.abort()
            }
        }
    }
}
