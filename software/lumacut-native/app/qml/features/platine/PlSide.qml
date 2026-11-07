import QtQuick
import QtQuick.Layouts
import LumaCut

// Right panel of Platine: settings, laser values per work stage, the steps at the bench; "Ins Projekt" at the foot.
Rectangle {
    id: root
    color: Theme.surface
    property string tab: "settings"
    readonly property var s: Platine.settings
    function de(v, d) { return Fmt.trim(v, d) }
    Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: Theme.line }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0
        LcTabs {
            objectName: "pcb-tabs"
            Layout.fillWidth: true
            tabs: [{ value: "settings", label: "Einstellungen" }, { value: "laser", label: "Lasern" }, { value: "steps", label: "Ablauf" }]
            value: root.tab
            onActivated: (v) => root.tab = v
        }

        // ---- Settings ----
        LcScroll {
            objectName: "pcb-settings"
            visible: root.tab === "settings"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp4

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Seite"; kind: "section" }
                LcSegmented {
                    objectName: "pcb-side"
                    Layout.fillWidth: true
                    options: [{ value: "top", label: "Oberseite" }, { value: "bottom", label: "Unterseite" }]
                    value: root.s.side
                    onActivated: (v) => Platine.set("side", v)
                }
                LcCheck { objectName: "pcb-mirror"; text: "Spiegeln"; checked: root.s.mirror; onToggled: (on) => Platine.set("mirror", on) }
                LcText {
                    text: "Gerber zeigt die Unterseite von oben durch die Platine. Damit sie unter dem Laser passt, wird sie gespiegelt."
                    kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true
                }
                LcNote { visible: root.s.side === "bottom" && Platine.boardInfo.hasBottom === false; tone: "warn"; text: "Für die Unterseite gibt es keine Kupferlage."; Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcCheck { objectName: "pcb-resist"; text: "Lack entfernen, danach ätzen"; checked: root.s.resist; onToggled: (on) => Platine.set("resist", on) }
                LcSegmented {
                    objectName: "pcb-method"
                    enabled: root.s.resist
                    Layout.fillWidth: true
                    options: [{ value: "raster", label: "Raster", tip: "Empfohlen" }, { value: "isolation", label: "Isolation", tip: "Schneller" },
                              { value: "expose", label: "Fotofilm", tip: "Nicht erprobt" }]
                    value: root.s.method
                    onActivated: (v) => Platine.set("method", v)
                }
                LcText {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    kind: "smallMuted"
                    text: root.s.method === "raster" ? "Der Laser entfernt den Lack überall außer auf dem Kupfer. Das Ätzbad nimmt danach alles freie Kupfer weg. Der übliche Weg bei Lack."
                        : root.s.method === "isolation" ? "Nur Trennbahnen um die Leiter. Das übrige Kupfer bleibt als Insel ohne Verbindung stehen. Spart Zeit und Ätzmittel."
                        : "Der Laser belichtet Negativ-Trockenfilm mit wenig Energie, entwickelt wird in Sodalösung. Ob der Film bei 450 nm reagiert, zeigt nur ein Probestreifen."
                }
                GridLayout {
                    visible: root.s.method === "isolation"
                    Layout.fillWidth: true
                    columns: 3
                    columnSpacing: Theme.sp2
                    LcField { label: "Bahnen"; Layout.fillWidth: true
                        LcNumber { objectName: "pcb-passes"; value: root.s.passes; min: 1; max: 20; digits: 0; onEdited: (v) => Platine.set("passes", Math.round(v)) } }
                    LcField { label: "Abstand"; Layout.fillWidth: true
                        LcNumber { objectName: "pcb-spacing"; value: root.s.passSpacingMm; min: 0.03; max: 2; step: 0.01; unit: "mm"; tip: "Von Bahn zu Bahn"; onEdited: (v) => Platine.set("passSpacingMm", v) } }
                    LcField { label: "Versatz"; Layout.fillWidth: true
                        LcNumber { objectName: "pcb-offset"; value: root.s.isolationOffsetMm; min: 0; max: 2; step: 0.01; unit: "mm"; tip: "Zusätzlicher Abstand der ersten Bahn zum Kupfer"; onEdited: (v) => Platine.set("isolationOffsetMm", v) } }
                }
                LcCheck { visible: root.s.method === "isolation"; objectName: "pcb-rest"; text: "Restkupfer auch entfernen"; checked: root.s.removeRest; onToggled: (on) => Platine.set("removeRest", on) }
                LcNote { visible: root.s.method === "expose"; tone: "warn"; text: "Dieser Weg ist hier nicht erprobt. Erst einen Probestreifen belichten und entwickeln."; Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Strahl"; kind: "section" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcField { label: "Strahlbreite"; Layout.fillWidth: true
                        LcNumber { objectName: "pcb-beam"; value: root.s.beamMm; min: 0.03; max: 1; step: 0.01; unit: "mm"; onEdited: (v) => Platine.set("beamMm", v) } }
                    LcField { label: "Überlappung"; Layout.fillWidth: true
                        LcNumber { objectName: "pcb-overlap"; value: root.s.overlapPct; min: 0; max: 80; step: 5; digits: 0; unit: "%"; onEdited: (v) => Platine.set("overlapPct", v) } }
                }
                LcText { text: "Zeilenabstand " + root.de(Platine.interval, 3) + " mm. Die Strahlbreite ist ein Startwert: mit der Linienbreite aus dem Materialtest ersetzen."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcCheck { objectName: "pcb-drillmarks"; text: "Bohrmarken"; checked: root.s.drillMarks; onToggled: (on) => Platine.set("drillMarks", on) }
                LcText { text: "Ein kleiner Punkt in der Padmitte wird mitgeätzt, der Bohrer findet dort von selbst die Mitte. Gebohrt wird von Hand."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                RowLayout {
                    visible: root.s.drillMarks
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcSegmented { objectName: "pcb-drillstyle"; options: [{ value: "dot", label: "Punkt" }, { value: "cross", label: "Kreuz" }]; value: root.s.drillStyle; onActivated: (v) => Platine.set("drillStyle", v) }
                    LcNumber { objectName: "pcb-drillsize"; value: root.s.drillMarkMm; min: 0.1; max: 2; step: 0.05; unit: "mm"; Layout.fillWidth: true; onEdited: (v) => Platine.set("drillMarkMm", v) }
                }
                LcNote { visible: Platine.hasBoard && Platine.boardInfo.drillCount === 0; tone: "warn"; text: "Keine Bohrdatei geladen, also gibt es keine Marken."; Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Passmarken"; kind: "section" }
                LcSegmented {
                    objectName: "pcb-fiducials"
                    Layout.fillWidth: true
                    options: [{ value: 0, label: "Keine" }, { value: 2, label: "Zwei" }, { value: 4, label: "Vier" }]
                    value: root.s.fiducials
                    onActivated: (v) => Platine.set("fiducials", v)
                }
                RowLayout {
                    visible: root.s.fiducials > 0
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcField { label: "Größe"; Layout.fillWidth: true
                        LcNumber { value: root.s.fiducialDiaMm; min: 0.3; max: 3; step: 0.1; unit: "mm"; onEdited: (v) => Platine.set("fiducialDiaMm", v) } }
                    LcField { label: "Abstand zum Rand"; Layout.fillWidth: true
                        LcNumber { value: root.s.fiducialOffsetMm; min: 1; max: 20; step: 0.5; unit: "mm"; onEdited: (v) => Platine.set("fiducialOffsetMm", v) } }
                }
                LcText { text: "Geätzte Punkte außerhalb des Umrisses, symmetrisch zur senkrechten Mitte. Aufgebohrt finden sie nach dem Wenden und beim Lötstopp dieselbe Lage wieder."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcText { text: "Weitere Arbeitsgänge"; kind: "section" }
                LcCheck { objectName: "pcb-mask"; text: "Lötstopp freilegen, nach dem Ätzen"; checked: root.s.mask; onToggled: (on) => Platine.set("mask", on) }
                LcCheck { objectName: "pcb-silk"; text: "Bestückungsdruck in den Lack markieren"; checked: root.s.silk; onToggled: (on) => Platine.set("silk", on) }
                LcCheck { objectName: "pcb-outline"; text: "Umriss als Sägehilfe markieren"; checked: root.s.outlineMark; onToggled: (on) => Platine.set("outlineMark", on) }
            }

            ColumnLayout {
                objectName: "pcb-checks"
                Layout.fillWidth: true
                spacing: Theme.sp2
                visible: Platine.checks.length > 0
                LcText { text: "Prüfung gegen " + root.de(root.s.beamMm, 2) + " mm Strahl"; kind: "section" }
                Repeater {
                    model: Platine.checks
                    LcNote { required property var modelData; tone: modelData.tone; text: modelData.title + ". " + modelData.text; Layout.fillWidth: true }
                }
            }
        }

        // ---- Laser values ----
        LcScroll {
            objectName: "pcb-laser"
            visible: root.tab === "laser"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp3
            LcNote { tone: "warn"; text: "Startwerte, nicht geprüft. Vorher Materialtest auf demselben Lack, dieselbe Schicht. Nie auf ungetestetem Lack lasern."; Layout.fillWidth: true }
            LcText { text: "Ebenen dieses Arbeitsgangs"; kind: "section" }
            Repeater {
                model: Platine.jobLayers
                ColumnLayout {
                    id: jl
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Theme.sp1
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.sp2
                        Rectangle { width: 10; height: 10; radius: 3; color: jl.modelData.color }
                        LcText { text: jl.modelData.name; font.weight: Font.Medium; Layout.fillWidth: true; elide: Text.ElideRight }
                        LcChip { text: jl.modelData.process }
                        LcText { text: jl.modelData.time; kind: "smallMuted"; tnum: true }
                    }
                    RowLayout {
                        visible: jl.modelData.first
                        Layout.fillWidth: true
                        spacing: Theme.sp2
                        LcField { label: "Leistung"; Layout.fillWidth: true
                            LcNumber { objectName: "pcb-power-" + jl.modelData.key; value: jl.modelData.power; min: 8; max: 100; digits: 0; unit: "%"; onEdited: (v) => Platine.setProcessValue(jl.modelData.key, "power", v) } }
                        LcField { label: "Tempo"; Layout.fillWidth: true
                            LcNumber { objectName: "pcb-speed-" + jl.modelData.key; value: jl.modelData.speed; min: 100; max: 12000; step: 100; digits: 0; unit: "mm/min"; onEdited: (v) => Platine.setProcessValue(jl.modelData.key, "speed", v) } }
                    }
                }
            }
            LcText { text: "Untergrenze 8 %: darunter zündet der Laser nicht sicher. Im Motiv lassen sich die Ebenen danach wie jede andere ändern."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcButton { icon: "flask-conical"; text: "Zum Materialtest in der Werkstatt"; onClicked: Shell.navigate("werkstatt") }
        }

        // ---- Steps at the bench ----
        LcScroll {
            objectName: "pcb-steps"
            visible: root.tab === "steps"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.sp3
            LcText { text: "Ablauf an der Werkbank"; kind: "section" }
            Repeater {
                model: Platine.workflow
                RowLayout {
                    id: st
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    spacing: Theme.sp3
                    Rectangle {
                        Layout.alignment: Qt.AlignTop
                        width: 22; height: 22; radius: 11
                        color: st.modelData.laser ? Theme.accentSoft : Theme.surface3
                        LcText { anchors.centerIn: parent; text: st.index + 1; kind: "small"; tnum: true; color: st.modelData.laser ? Theme.accent : Theme.muted }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        LcText { text: st.modelData.title + (st.modelData.laser ? "  ·  Laser" : ""); font.weight: Font.DemiBold; Layout.fillWidth: true }
                        LcText { text: st.modelData.text; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
            LcText { text: "Das geht mit dieser Diode nicht"; kind: "section" }
            LcText { text: "Kupfer abtragen: Kupfer wirft 450 nm fast ganz zurück und leitet die Wärme weg. Deshalb wird nur Lack entfernt und danach geätzt."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { text: "FR4 schneiden: Das Epoxid verkohlt und qualmt giftig, die Glasfaser bleibt. Platine sägen oder ritzen und brechen."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { text: "Löcher bohren: Der Laser setzt nur die Marke."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
            LcText { text: "Sicherheit"; kind: "section" }
            LcText { text: "Lack- und Epoxiddampf nicht einatmen: Abluft an, Deckel zu, Brille für 450 nm."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { text: "Ätzmittel: Handschuhe und Schutzbrille, gut lüften, nur Kunststoff- oder Glasschale. Persulfat gast aus, nie dicht verschließen."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { text: "Verbrauchte Ätzlösung enthält Kupfer: zur Schadstoffsammlung, nicht in den Ausguss."; kind: "smallMuted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { text: "Stand aus Physik und Berichten von Bastlern, auf dieser Maschine noch nicht erprobt."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }

        // ---- Foot: work stage and the one action ----
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.sp4
            spacing: Theme.sp3
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.sp2
                LcSegmented {
                    objectName: "pcb-stage"
                    visible: Platine.stages.length > 1
                    options: Platine.stages
                    value: Platine.stage
                    onActivated: (v) => Platine.setStage(v)
                }
                LcText { visible: Platine.stages.length <= 1; text: "Arbeitsgang Ätzresist"; kind: "smallMuted" }
                Item { Layout.fillWidth: true }
                LcText { objectName: "pcb-time"; text: Platine.jobTime.length ? "etwa " + Platine.jobTime : ""; kind: "smallMuted"; tnum: true }
            }
            LcChip { visible: Platine.badCount > 0; tone: "bad"; text: Platine.badCount === 1 ? "1 Problem, siehe Prüfung" : Platine.badCount + " Probleme, siehe Prüfung" }
            LcButton {
                objectName: "pcb-to-project"
                Layout.fillWidth: true
                variant: "primary"
                size: "lg"
                icon: "arrow-right"
                text: "Ins Projekt"
                tip: "Legt die Platine auf eine eigene Platte, weiter unter Starten"
                enabled: Platine.hasBoard && Platine.jobLayers.length > 0 && !Platine.busy
                onClicked: Platine.toProject()
            }
        }
    }
}
