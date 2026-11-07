import QtQuick
import QtQuick.Layouts
import LumaCut

// Right panel of the Lochraster mode: board and marking, the selected item, checks, parts list and assembly assistant.
Rectangle {
    id: root
    color: Theme.surface
    property string tab: "board"
    readonly property var b: Perfboard.board
    readonly property var o: Perfboard.options
    readonly property var sel: Perfboard.selection
    function de(v, d) { return Fmt.trim(v, d) }
    onSelChanged: {
        refIn.text = sel.ref || ""
        valIn.text = sel.value || ""
        textIn.text = sel.text || ""
    }
    Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: Theme.line }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0
        LcTabs {
            objectName: "pf-tabs"
            Layout.fillWidth: true
            // Short labels when the panel is narrow, so all four tabs stay reachable. The labels are separate string
            // properties: they notify only on a real change, so the tab strip is not rebuilt under the mouse on every edit.
            readonly property bool narrow: width < 360
            readonly property string selLabel: narrow ? "Teil" : root.sel.kind === "part" ? "Auswahl " + root.sel.ref : "Auswahl"
            readonly property string checkLabel: (narrow ? "Prüfen" : "Prüfung") + (Perfboard.badCount > 0 ? " (" + Perfboard.badCount + ")" : "")
            readonly property string bomLabel: narrow ? "Bestücken" : "Bestückung"
            tabs: [{ value: "board", label: "Platine" }, { value: "sel", label: selLabel }, { value: "check", label: checkLabel }, { value: "bom", label: bomLabel }]
            value: root.tab
            onActivated: (v) => root.tab = v
        }

        // ---- Board, bed position, marking ----
        LcScroll {
            objectName: "pf-board-tab"
            visible: root.tab === "board"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp4
            LcNote { objectName: "pf-note"; visible: (root.b.note || "").length > 0; tone: "warn"; text: root.b.note || ""; Layout.fillWidth: true }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Platine"; kind: "section" }
                LcSegmented {
                    objectName: "pf-template"
                    Layout.fillWidth: true
                    options: Perfboard.templates
                    value: Perfboard.templates.findIndex(t => t.label === root.b.name.replace(/ /g, ""))
                    onActivated: (v) => Perfboard.setTemplate(v)
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: Theme.sp2
                    rowSpacing: Theme.sp2
                    LcField { label: "Breite"; Layout.fillWidth: true; LcNumber { value: root.b.width; min: 10; max: 300; step: 1; digits: 1; unit: "mm"; onEdited: (v) => Perfboard.setBoard("width", v) } }
                    LcField { label: "Höhe"; Layout.fillWidth: true; LcNumber { value: root.b.height; min: 10; max: 300; step: 1; digits: 1; unit: "mm"; onEdited: (v) => Perfboard.setBoard("height", v) } }
                    LcField { label: "Spalten"; Layout.fillWidth: true; LcNumber { value: root.b.cols; min: 2; max: 120; digits: 0; onEdited: (v) => Perfboard.setBoard("cols", v) } }
                    LcField { label: "Zeilen"; Layout.fillWidth: true; LcNumber { value: root.b.rows; min: 2; max: 120; digits: 0; onEdited: (v) => Perfboard.setBoard("rows", v) } }
                    LcField { label: "Raster"; Layout.fillWidth: true; LcNumber { value: root.b.pitch; min: 1; max: 5.08; step: 0.01; unit: "mm"; onEdited: (v) => Perfboard.setBoard("pitch", v) } }
                    LcField { label: "Pad-Ø"; Layout.fillWidth: true; LcNumber { value: root.b.padDia; min: 0.5; max: 4; step: 0.1; unit: "mm"; onEdited: (v) => Perfboard.setBoard("padDia", v) } }
                    LcField { label: "Bohrung"; Layout.fillWidth: true; LcNumber { value: root.b.holeDia; min: 0.3; max: 3; step: 0.1; unit: "mm"; onEdited: (v) => Perfboard.setBoard("holeDia", v) } }
                    LcField { label: "Befestigung Ø / Abstand"; Layout.fillWidth: true
                        RowLayout { spacing: Theme.sp1
                            LcNumber { Layout.fillWidth: true; value: root.b.mountDia; min: 0; max: 5; step: 0.1; unit: "mm"; onEdited: (v) => Perfboard.setBoard("mountDia", v) }
                            LcNumber { Layout.fillWidth: true; value: root.b.mountInset; min: 0; max: 15; step: 0.5; unit: "mm"; onEdited: (v) => Perfboard.setBoard("mountInset", v) } } }
                }
                LcCheck { text: "Oben und unten je eine Reihe Langlochpads"; checked: root.b.edgeRows; onToggled: (on) => Perfboard.setBoard("edgeRows", on) }
                LcText { text: root.b.grid + ". Alle Werte sind Vorgaben: mit dem Messschieber an der eigenen Platine prüfen."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Lage auf dem Bett"; kind: "section" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcField { label: "Mitte X"; Layout.fillWidth: true; LcNumber { objectName: "pf-bed-x"; value: Perfboard.bedX; min: 0; max: 600; step: 0.5; digits: 1; unit: "mm"; onEdited: (v) => Perfboard.setBed(v, Perfboard.bedY) } }
                    LcField { label: "Mitte Y"; Layout.fillWidth: true; LcNumber { objectName: "pf-bed-y"; value: Perfboard.bedY; min: 0; max: 600; step: 0.5; digits: 1; unit: "mm"; onEdited: (v) => Perfboard.setBed(Perfboard.bedX, v) } }
                }
                LcNote {
                    Layout.fillWidth: true
                    text: "Zuerst die Halterung mit der Tasche in der Werkstatt schneiden und danach nicht mehr verschieben. Für die Lötseite die Platine um ihre senkrechte Mittelachse wenden, dann passt sie wieder in dieselbe Tasche."
                }
                LcButton { icon: "hammer"; text: "Halterung in der Werkstatt"; onClicked: Shell.navigate("werkstatt") }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Markieren"; kind: "section" }
                LcText {
                    text: "Der Laser verfärbt oder entfernt nur den Lötstopplack. Zwischen den Pads ist kein Kupfer, deshalb entstehen keine Leiterbahnen: Verbindungen sind Lötbrücken oder Drähte, die Markierung zeigt nur ihren Weg. Pads bleiben frei. Geschnitten wird nie, FR4 lässt sich mit der Diode nicht sauber trennen und setzt schädliche Dämpfe frei."
                    kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true
                }
                LcCheck { objectName: "pf-refs"; text: "Referenzen (R1, C1 …)"; checked: root.o.markRefs; onToggled: (on) => Perfboard.setOption("markRefs", on) }
                LcCheck { objectName: "pf-values"; text: "Werte (10k …)"; checked: root.o.markValues; onToggled: (on) => Perfboard.setOption("markValues", on) }
                LcCheck { objectName: "pf-holes"; text: "Lochnummern A, B … und 1, 2 … am Rand"; checked: root.o.holeNumbers === true; onToggled: (on) => Perfboard.setOption("holeNumbers", on) }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    columnSpacing: Theme.sp2
                    LcField { label: "Strahl"; Layout.fillWidth: true; LcNumber { value: root.o.beamMm; min: 0.03; max: 1; step: 0.01; unit: "mm"; onEdited: (v) => Perfboard.setOption("beamMm", v) } }
                    LcField { label: "Rand ums Pad"; Layout.fillWidth: true; LcNumber { value: root.o.padClearMm; min: 0.05; max: 1; step: 0.05; unit: "mm"; onEdited: (v) => Perfboard.setOption("padClearMm", v) } }
                    LcField { label: "Schrift"; Layout.fillWidth: true; LcNumber { value: root.o.textMm; min: 0.5; max: 5; step: 0.1; unit: "mm"; onEdited: (v) => Perfboard.setOption("textMm", v) } }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcField { label: "Leistung"; Layout.fillWidth: true; LcNumber { objectName: "pf-power"; value: root.o.power; min: 8; max: 100; digits: 0; unit: "%"; onEdited: (v) => Perfboard.setOption("power", v) } }
                    LcField { label: "Tempo"; Layout.fillWidth: true; LcNumber { value: root.o.speed; min: 100; max: 12000; step: 100; digits: 0; unit: "mm/min"; onEdited: (v) => Perfboard.setOption("speed", v) } }
                }
                LcNote { Layout.fillWidth: true; tone: "warn"; text: "Startwert, ungeprüft. Für Lötstopplack gibt es noch keine gemessenen Werte: zuerst Materialtest auf einem Reststück. Abluft an." }
            }
        }

        // ---- Selected item ----
        LcScroll {
            objectName: "pf-sel-tab"
            visible: root.tab === "sel"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp3
            LcText {
                visible: root.sel.kind === "none"
                text: "Nichts ausgewählt. Ein Bauteil, eine Verbindung oder einen Text auf der Platine anklicken."
                kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            ColumnLayout {
                visible: root.sel.kind === "part"
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: root.sel.name || ""; kind: "h3" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcField { label: "Referenz"; Layout.fillWidth: true
                        LcInput { id: refIn; objectName: "pf-ref"; onAccepted: commit(); input.onActiveFocusChanged: if (!input.activeFocus) commit()
                            function commit() { if (text !== (root.sel.ref || "")) Perfboard.setSelValue("ref", text) } } }
                    LcField { label: "Wert"; Layout.fillWidth: true
                        LcInput { id: valIn; objectName: "pf-value"; onAccepted: commit(); input.onActiveFocusChanged: if (!input.activeFocus) commit()
                            function commit() { if (text !== (root.sel.value || "")) Perfboard.setSelValue("value", text) } } }
                }
                LcStat { label: "Pins"; value: root.sel.pins || ""; mono: false }
                LcStat { label: "Drehung"; value: (root.sel.rot || 0) + "°"; mono: false }
                LcText { visible: (root.sel.hint || "").length > 0; text: root.sel.hint || ""; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            ColumnLayout {
                visible: root.sel.kind === "wire"
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Verbindung " + (root.sel.from || "") + " → " + (root.sel.to || ""); kind: "h3" }
                LcText { visible: (root.sel.net || "").length > 0 || root.sel.thick === true; text: (root.sel.net ? "Netz " + root.sel.net : "") + (root.sel.thick ? (root.sel.net ? ", " : "") + "dicke Leitung: als Doppellinie markiert" : ""); kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                LcSegmented {
                    Layout.fillWidth: true
                    options: [{ value: true, label: "Lötseite (Lötbrücke)" }, { value: false, label: "Bestückungsseite (Draht)" }]
                    value: root.sel.solder
                    onActivated: (v) => Perfboard.setSelValue("solder", v)
                }
                LcText { text: "Die Markierung läuft in der Lackgasse neben den Löchern. Gelötet wird von Loch zu Loch."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            ColumnLayout {
                visible: root.sel.kind === "label"
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Beschriftung"; kind: "h3" }
                LcField { label: "Text"; Layout.fillWidth: true
                    LcInput { id: textIn; objectName: "pf-text"; onAccepted: commit(); input.onActiveFocusChanged: if (!input.activeFocus) commit()
                        function commit() { if (text !== (root.sel.text || "")) Perfboard.setSelValue("text", text) } } }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcField { label: "Höhe"; Layout.fillWidth: true; LcNumber { value: root.sel.height || 1.5; min: 0.3; max: 20; step: 0.1; unit: "mm"; onEdited: (v) => Perfboard.setSelValue("height", v) } }
                    LcSegmented { Layout.alignment: Qt.AlignBottom; options: [{ value: false, label: "Oben" }, { value: true, label: "Lötseite" }]; value: root.sel.solder; onActivated: (v) => Perfboard.setSelValue("solder", v) }
                }
                LcText { text: "Mindesthöhe beim Strahl: " + root.de(root.o.minText, 1) + " mm. Über den Pads geht Schrift verloren, am Rand bleibt sie ganz."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            RowLayout {
                visible: root.sel.kind !== "none"
                spacing: Theme.sp2
                LcButton { visible: root.sel.kind === "part"; objectName: "pf-rotate"; icon: "rotate-cw"; text: "Drehen"; tip: "R"; onClicked: Perfboard.rotateSelected() }
                LcButton { objectName: "pf-delete"; icon: "trash-2"; text: "Löschen"; tip: "Entf"; onClicked: Perfboard.deleteSelected() }
            }
        }

        // ---- Checks ----
        LcScroll {
            objectName: "pf-check-tab"
            visible: root.tab === "check"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp2
            Repeater {
                model: Perfboard.checks
                LcNote { required property var modelData; tone: modelData.tone; text: modelData.text; Layout.fillWidth: true }
            }
            LcText { text: "Die Prüfung rechnet mit dem Raster und der Bibliothek, nicht mit den echten Bauteilen: Beinabstände im Datenblatt nachsehen."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }

        // ---- Parts list and assistant ----
        LcScroll {
            objectName: "pf-bom-tab"
            visible: root.tab === "bom"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp3
            LcText { text: "Stückliste"; kind: "section" }
            LcText { visible: Perfboard.bomRows.length === 0; text: "Noch keine Bauteile auf der Platine."; kind: "muted" }
            Repeater {
                model: Perfboard.bomRows
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcText { text: modelData.count + "×"; tnum: true; font.weight: Font.DemiBold; Layout.preferredWidth: 26 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        LcText { text: modelData.part + (modelData.value.length ? ", " + modelData.value : ""); Layout.fillWidth: true; elide: Text.ElideRight }
                        LcText { text: modelData.refs; kind: "smallFaint"; Layout.fillWidth: true; elide: Text.ElideRight }
                    }
                }
            }
            RowLayout {
                spacing: Theme.sp2
                LcButton { size: "sm"; icon: "image"; text: "PNG"; onClicked: Perfboard.askExport("png") }
                LcButton { size: "sm"; icon: "download"; text: "SVG"; onClicked: Perfboard.askExport("svg") }
                LcButton { size: "sm"; icon: "download"; text: "CSV"; onClicked: Perfboard.askExport("csv") }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
            LcText { text: "Bestücken Schritt für Schritt"; kind: "section" }
            LcText { text: "Flache Teile zuerst, hohe zuletzt. Das aktuelle Bauteil ist auf der Platine hervorgehoben."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcButton { visible: Perfboard.assistStep < 0; objectName: "pf-assist-start"; icon: "play"; text: "Assistent starten"; enabled: Perfboard.parts.length > 0; onClicked: Perfboard.startAssist() }
            LcCard {
                id: assistCard
                visible: Perfboard.assistStep >= 0 && Perfboard.assistStep < Perfboard.assistItems.length
                Layout.fillWidth: true
                readonly property var it: Perfboard.assistItems[Math.max(0, Perfboard.assistStep)] || ({})
                LcText { objectName: "pf-assist-title"; text: "Schritt " + (Perfboard.assistStep + 1) + " von " + Perfboard.assistItems.length + ": " + (assistCard.it.ref || ""); kind: "h3" }
                LcText { text: (assistCard.it.name || "") + (assistCard.it.value ? ", " + assistCard.it.value : "") + ", Pin 1 auf " + (assistCard.it.at || ""); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                LcText { visible: (assistCard.it.hint || "").length > 0; text: assistCard.it.hint || ""; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Flow {
                    // Wraps in a narrow panel, so "Beenden" stays reachable.
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcButton { icon: "arrow-left"; text: "Zurück"; enabled: Perfboard.assistStep > 0; onClicked: Perfboard.assistGo(Perfboard.assistStep - 1) }
                    LcButton { objectName: "pf-assist-next"; variant: "primary"; icon: "check"; text: "Eingelötet, weiter"; onClicked: { Perfboard.toggleDone(Perfboard.assistStep); Perfboard.assistGo(Perfboard.assistStep + 1) } }
                    LcButton { objectName: "pf-assist-stop"; variant: "ghost"; text: "Beenden"; onClicked: Perfboard.stopAssist() }
                }
            }
            Repeater {
                model: Perfboard.assistItems
                LcCheck {
                    required property var modelData
                    required property int index
                    text: modelData.ref + "  " + modelData.name + (modelData.value ? ", " + modelData.value : "")
                    checked: modelData.done
                    onToggled: Perfboard.toggleDone(index)
                    Layout.fillWidth: true
                }
            }
        }

        // ---- Foot ----
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.sp4
            spacing: Theme.sp2
            LcChip { visible: Perfboard.badCount > 0; tone: "bad"; text: Perfboard.badCount === 1 ? "1 Problem, siehe Prüfung" : Perfboard.badCount + " Probleme, siehe Prüfung" }
            LcText { text: "Zwei Platten: Bestückungsseite und Lötseite (gespiegelt), beide nur Markieren."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcButton {
                objectName: "pf-to-project"
                Layout.fillWidth: true
                variant: "primary"
                size: "lg"
                icon: "arrow-right"
                text: "Ins Projekt"
                tip: "Markierungen auf zwei Platten, weiter unter Starten"
                enabled: { Perfboard.revision; return Perfboard.parts.length > 0 || Perfboard.info().wires > 0 }
                onClicked: Perfboard.toProject()
            }
        }
    }
}
