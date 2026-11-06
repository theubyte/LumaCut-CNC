import QtQuick
import QtQuick.Layouts
import LumaCut

// List of what is measured, details on the right. Assistants that need the tablet's image analysis say so.
LcScroll {
    id: page
    objectName: "m-kal"
    property string sel: AppSettings.value("kalSel", "kamera")
    readonly property var items: Calibration.items
    readonly property var cur: { for (const i of items) if (i.id === sel) return i; return items[0] }
    readonly property string notYet: "Der Assistent braucht die Bildauswertung der Tablet-App und kommt in einer späteren Etappe. Bis dahin dort messen; das Ergebnis liegt auf dem Pi und erscheint hier."
    Component.onCompleted: { Calibration.loadCamera(); Calibration.loadBedMap() }
    maxContentWidth: 1096
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.sp4
        LcCard {
            objectName: "kal-list"
            Layout.preferredWidth: 320
            Layout.alignment: Qt.AlignTop
            padding: Theme.sp2
            spacing: 0
            Repeater {
                model: ["Grundlagen", "Je Material"]
                ColumnLayout {
                    id: grp
                    required property string modelData
                    Layout.fillWidth: true
                    spacing: 0
                    LcText { text: grp.modelData; kind: "section"; Layout.margins: Theme.sp2; Layout.bottomMargin: Theme.sp1 }
                    Repeater {
                        model: page.items.filter((i) => i.group === grp.modelData)
                        Rectangle {
                            id: entry
                            required property var modelData
                            objectName: "kal-" + modelData.id
                            readonly property bool on: modelData.id === page.cur.id
                            Layout.fillWidth: true
                            implicitHeight: rowE.implicitHeight + 16
                            radius: Theme.rMd
                            color: on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
                            RowLayout {
                                id: rowE
                                anchors.fill: parent; anchors.margins: 8
                                spacing: Theme.sp2
                                LcIcon {
                                    Layout.preferredWidth: 16; Layout.preferredHeight: 16
                                    size: 16
                                    name: entry.modelData.tone === "ok" ? "check-circle-2" : entry.modelData.tone === "bad" ? "x-circle" : "circle-dashed"
                                    color: entry.modelData.tone === "ok" ? Theme.ok : entry.modelData.tone === "bad" ? Theme.bad : entry.modelData.tone === "warn" ? Theme.warn : Theme.faint
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    LcText { text: entry.modelData.title; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                                    LcText { text: entry.modelData.value; kind: "smallMuted"; tnum: true; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                                LcIcon { Layout.preferredWidth: 14; Layout.preferredHeight: 14; size: 14; name: "chevron-right"; color: Theme.faint }
                            }
                            MouseArea {
                                id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { page.sel = entry.modelData.id; AppSettings.setValue("kalSel", entry.modelData.id) }
                            }
                        }
                    }
                }
            }
        }
        LcCard {
            objectName: "kal-detail"
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            RowLayout {
                Layout.fillWidth: true
                LcText { objectName: "kal-title"; text: page.cur ? page.cur.title : ""; kind: "h2"; Layout.fillWidth: true }
                LcChip { text: page.cur ? page.cur.state : ""; tone: page.cur && page.cur.tone !== "off" ? page.cur.tone : "" }
            }
            Loader {
                Layout.fillWidth: true
                sourceComponent: !page.cur ? null : ({ kamera: cameraDetail, licht: lightDetail, taster: probeDetail, fokus: focusDetail, bewegung: motionDetail, bett: bedDetail, material: matcalDetail })[page.cur.id]
            }
        }
    }

    readonly property var st: Machine.status
    readonly property var cfg: st.config || ({})
    readonly property var cal: Calibration.calibration
    readonly property var cam: Calibration.camera
    readonly property var and: cal.android || ({})

    component Stats: GridLayout {
        Layout.fillWidth: true
        columns: width > 560 ? 4 : 2
        columnSpacing: Theme.sp4
        rowSpacing: Theme.sp3
    }
    component Sub: LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1 }
    component Para: LcText { kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    component Fine: LcText { kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }

    Component {
        id: cameraDetail
        ColumnLayout {
            spacing: Theme.sp3
            Para { text: "Misst Linse, Maßstab und Lage der Kamera zum Laser. Grundlage für Scan und Materialtest." }
            Stats {
                visible: Calibration.cameraOk
                Sub { label: "Bildgröße"; value: (page.and.photoWidth || page.cal.image_width) + " × " + (page.and.photoHeight || page.cal.image_height) + " px" }
                Sub { label: "Genauigkeit"; value: page.and.lens && Fmt.isNumber(page.and.lens.rmsMm) ? Fmt.de(page.and.lens.rmsMm, 2) + " mm" : "ohne Linsenmodell" }
                Sub { label: "Scanhöhe"; value: Fmt.isNumber(page.and.scanZ) ? "Z " + Fmt.de(page.and.scanZ) + " mm" : Fmt.isNumber(page.cal.scan_z) ? "Z " + Fmt.de(page.cal.scan_z) + " mm" : "–" }
                Sub { mono: false; label: "Stand"; value: Fmt.when(page.cal.updated_at) }
            }
            LcNote { visible: !Calibration.cameraOk; tone: "warn"; text: "Noch keine Messung auf dem Pi."; Layout.fillWidth: true }
            Fine { text: page.notYet }
        }
    }
    Component {
        id: lightDetail
        ColumnLayout {
            spacing: Theme.sp3
            Para { text: "Feste Kamerawerte, damit die Bilder eines Scans gleich hell und gleich farbig sind." }
            Stats {
                Sub { label: "Weißabgleich"; value: Fmt.isNumber(page.cam.white_balance) ? page.cam.white_balance + " K" : "automatisch" }
                Sub { label: "Belichtung"; value: Fmt.isNumber(page.cam.exposure) ? page.cam.exposure : "automatisch" }
                Sub { label: "Verstärkung"; value: Fmt.isNumber(page.cam.gain) ? page.cam.gain : "automatisch" }
                Sub { label: "Licht beim Scan"; value: Fmt.isNumber(page.cam.light) ? page.cam.light + " %" : "wie eingestellt" }
            }
            Fine { text: "Belichtung und Weißabgleich lassen sich im Reiter Kamera von Hand setzen. Der Randabfall wird in der Tablet-App gemessen." }
        }
    }
    Component {
        id: probeDetail
        ColumnLayout {
            id: pd
            spacing: Theme.sp3
            readonly property var off: page.st.probe_xy_offset_mm
            Para { text: "So weit liegt die Tasterspitze neben dem Laserpunkt. Ohne diesen Wert tastet der Pi nicht ab." }
            Stats {
                Sub { label: "Versatz X"; value: pd.off ? Fmt.de(pd.off[0]) + " mm" : "–"; tone: pd.off ? "" : "bad" }
                Sub { label: "Versatz Y"; value: pd.off ? Fmt.de(pd.off[1]) + " mm" : "–"; tone: pd.off ? "" : "bad" }
                Sub { mono: false; label: "Taster in Firmware"; value: page.st.z_probe_supported === false ? "Nein" : page.st.z_probe_supported ? "Ja" : "unbekannt" }
            }
            RowLayout { LcButton { objectName: "probe-edit"; text: "Werte eintragen"; onClicked: probeDlg.open = true } }
            Fine { text: "Einmessen mit gelasertem Kreuz geht bisher in der Tablet-App. Hier lassen sich bekannte Werte eintragen." }
            MSettingsDialog {
                id: probeDlg
                objectName: "probeDialog"
                title: "Taster-Versatz"
                note: "Der Pi vergisst dabei die gemessene Werkstückoberfläche."
                fields: [{ key: "probe_offset_x_mm", label: "Versatz X", value: pd.off ? pd.off[0] : 0, min: -80, max: 80 }, { key: "probe_offset_y_mm", label: "Versatz Y", value: pd.off ? pd.off[1] : 0, min: -80, max: 80 }]
            }
        }
    }
    Component {
        id: focusDetail
        ColumnLayout {
            spacing: Theme.sp3
            Para { text: "Abstand von der Werkstückoberfläche, in dem der Laserpunkt am kleinsten ist." }
            Stats {
                Sub { label: "Fokusabstand"; value: Fmt.de(page.cfg.focus_gap_mm) + " mm" }
                Sub { label: "Schalter zu Spitze"; value: Fmt.de(page.cfg.z_switch_tip_offset_mm) + " mm" }
                Sub { label: "Z-Rückzug"; value: Fmt.de(page.cfg.z_clearance_mm) + " mm" }
                Sub { label: "Fokus Z jetzt"; value: Fmt.isNumber(page.st.laser_focus_z) ? Fmt.de(page.st.laser_focus_z, 2) + " mm" : "–" }
            }
            RowLayout { LcButton { objectName: "focus-edit"; text: "Werte eintragen"; onClicked: focusDlg.open = true } }
            Fine { text: page.notYet }
            MSettingsDialog {
                id: focusDlg
                objectName: "focusDialog"
                title: "Fokus und Höhen"
                note: "Der Pi vergisst dabei die gemessene Werkstückoberfläche. Falsche Werte führen zu unscharfen Schnitten, im Zweifel unverändert lassen."
                fields: [{ key: "focus_gap_mm", label: "Fokusabstand", value: page.cfg.focus_gap_mm || 0, min: 0.1, max: 30 }, { key: "z_switch_tip_offset_mm", label: "Schalter zu Spitze", value: page.cfg.z_switch_tip_offset_mm || 0, min: -20, max: 20 }, { key: "z_clearance_mm", label: "Z-Rückzug", value: page.cfg.z_clearance_mm || 20, min: 0.5, max: 50 }]
            }
        }
    }
    Component {
        id: motionDetail
        ColumnLayout {
            id: md
            spacing: Theme.sp3
            readonly property var stored: page.cfg.motion
            property real accel: stored && stored.accel ? stored.accel : 1000
            property real speed: stored && stored.speed ? stored.speed : 100
            property real span: 40
            property int cycles: 6
            Para { text: "Beschleunigung und Tempo für X und Y. Aufträge fahren damit, der Anlauf beim Gravieren wird daraus berechnet." }
            Stats {
                Sub { label: "Beschleunigung"; valueName: "motion-accel"; value: md.stored && md.stored.accel ? Fmt.de(md.stored.accel, 0) + " mm/s²" : "500 mm/s² (Firmware)" }
                Sub { label: "Tempo"; value: md.stored && md.stored.speed ? Fmt.de(md.stored.speed, 0) + " mm/s" : "150 mm/s (Firmware)" }
            }
            LcText { text: "Testfahrt mit dem Laser aus"; kind: "section"; Layout.topMargin: Theme.sp2 }
            GridLayout {
                Layout.fillWidth: true
                columns: 4; columnSpacing: Theme.sp3
                LcField { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Beschleunigung"; LcNumber { objectName: "motion-a"; value: md.accel; min: 100; max: 20000; step: 100; digits: 0; unit: "mm/s²"; onEdited: (v) => md.accel = v } }
                LcField { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Tempo"; LcNumber { objectName: "motion-s"; value: md.speed; min: 10; max: 500; step: 10; digits: 0; unit: "mm/s"; onEdited: (v) => md.speed = v } }
                LcField { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Weg"; LcNumber { value: md.span; min: 5; max: 120; step: 5; digits: 0; unit: "mm"; onEdited: (v) => md.span = v } }
                LcField { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Wiederholungen"; LcNumber { value: md.cycles; min: 1; max: 30; digits: 0; onEdited: (v) => md.cycles = v } }
            }
            MLockLine { text: Machine.moveLock }
            RowLayout {
                spacing: Theme.sp2
                LcButton {
                    objectName: "motion-test"; variant: "primary"; text: "Testfahrt starten"
                    lock: Machine.moveLock; busy: MachineActions.busyOp === "motion_test"
                    onClicked: Calibration.motionTest(md.accel, md.speed, md.span, md.cycles)
                }
                LcButton { objectName: "motion-save"; text: "Diese Werte speichern"; lock: Machine.moveLock; onClicked: Calibration.motionSave(md.accel, md.speed) }
                LcButton { objectName: "motion-reset"; visible: !!(md.stored && md.stored.accel); variant: "ghost"; text: "Firmware-Werte"; lock: Machine.moveLock; onClicked: Calibration.motionReset() }
            }
            Fine { text: "Die Testfahrt um die aktuelle Kopfposition zeigt keinen Schrittverlust von selbst: Danach an einer Marke prüfen. Die automatische Messung mit Prüfmarken und Kamera läuft bisher in der Tablet-App." }
        }
    }
    Component {
        id: bedDetail
        ColumnLayout {
            id: bd
            spacing: Theme.sp3
            readonly property var summary: page.st.bed_map
            readonly property var cells: Calibration.bedCells(Calibration.bedMap)
            Para { text: "Höhenprofil des leeren Betts, damit Stärke und Höhenkorrektur stimmen." }
            Stats {
                visible: !!bd.summary
                Sub { label: "Punkte"; valueName: "bed-points"; value: bd.summary ? bd.summary.cols + " × " + bd.summary.rows : "" }
                Sub { label: "Spanne"; value: bd.summary ? Fmt.de(bd.summary.range, 2) + " mm" : "" }
                Sub { label: "Tiefster, höchster Punkt"; value: bd.summary ? Fmt.de(bd.summary.lowest, 2) + " bis " + Fmt.de(bd.summary.highest, 2) + " mm" : "" }
                Sub { mono: false; label: "Gemessen"; value: bd.summary ? Fmt.when(bd.summary.measured_at) : "" }
            }
            LcNote { visible: !bd.summary; tone: "warn"; text: "Noch nicht gemessen."; Layout.fillWidth: true }
            Grid {
                objectName: "bed-grid"
                visible: bd.cells.length > 0
                Layout.fillWidth: true
                columns: Math.max(1, Calibration.bedMap.cols || 1)
                spacing: 2
                Repeater {
                    model: bd.cells
                    Rectangle {
                        required property var modelData
                        width: (parent.width - 2 * (parent.columns - 1)) / parent.columns
                        height: 24
                        radius: 3
                        color: Qt.tint(Theme.surface2, Qt.alpha(Theme.accent, modelData.level * .45 + .04))
                        LcText { anchors.centerIn: parent; text: parent.modelData.text; kind: "mono"; font.pixelSize: Theme.fsXs }
                    }
                }
            }
            MLockLine { text: Machine.probeLock }
            RowLayout {
                spacing: Theme.sp2
                LcButton {
                    objectName: "bed-measure"; variant: "primary"; text: bd.summary ? "Neu messen" : "Messen"
                    lock: Machine.probeLock; busy: MachineActions.busyOp === "bedmap"
                    onClicked: MachineActions.run("bedmap")
                }
                LcButton { objectName: "bed-clear"; visible: !!bd.summary; variant: "ghost"; text: "Löschen"; onClicked: Calibration.clearBedMap() }
            }
            Fine { text: "Das Bett muss dafür leer sein, der Pi prüft das nicht." }
        }
    }
    Component {
        id: matcalDetail
        ColumnLayout {
            id: mc
            spacing: Theme.sp3
            property string kind: "engrave"
            property bool raised: false
            readonly property var last: page.st.material_calibration
            readonly property string lock: Calibration.matcalLock(kind, raised, [Machine.status, Workspace.hasMaterial, Calibration.cameraOk])
            Para { text: "Der Pi lasert, fotografiert und misst selbst, bis die Werte sitzen, und speichert sie als Material. Kopf vorher über eine freie, glatte Stelle fahren: Der Test beginnt am Laserpunkt." }
            RowLayout {
                spacing: Theme.sp3
                LcSegmented {
                    objectName: "matcal-kind"
                    value: mc.kind
                    options: [{ value: "engrave", label: "Gravur" }, { value: "cut", label: "Schnitt" }]
                    onActivated: (v) => mc.kind = v
                }
                LcCheck { objectName: "matcal-raised"; visible: mc.kind === "cut"; checked: mc.raised; text: "Platte liegt auf Abstandhaltern, etwa 10 mm Luft"; onToggled: (on) => mc.raised = on }
            }
            Stats {
                Sub { mono: false; label: "Material"; value: Workspace.hasMaterial ? Workspace.materialName + ", " + Fmt.de(Workspace.materialThickness) + " mm" : "keins gewählt"; tone: Workspace.hasMaterial ? "" : "warn" }
                Sub { mono: false; label: "Testbereich"; value: mc.kind === "engrave" ? "51 × 21 mm ab Kopf" : "56 × 8 mm ab Kopf" }
            }
            MLockLine { text: mc.lock }
            RowLayout {
                LcButton {
                    objectName: "matcal-start"; variant: "primary"; text: "Materialtest starten"
                    lock: mc.lock; busy: MachineActions.busyOp === "matcal"
                    onClicked: Calibration.startMatcal(mc.kind, mc.raised)
                }
            }
            ColumnLayout {
                visible: !!mc.last
                objectName: "matcal-last"
                Layout.fillWidth: true
                spacing: Theme.sp2
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                LcText { kind: "section"; text: mc.last ? "Letzter Test: " + (mc.last.kind === "engrave" ? "Gravur" : "Schnitt") + ", " + mc.last.material : "" }
                LcText { visible: !!mc.last && mc.last.state === "running"; kind: "muted"; text: mc.last ? "Läuft, Schritt " + (mc.last.steps || 0) + "." : "" }
                Repeater {
                    model: ["dunkel", "mittel", "hell"]
                    LcText {
                        required property string modelData
                        readonly property var r: mc.last && mc.last.result ? mc.last.result[modelData] : null
                        visible: !!r
                        tnum: true
                        text: r ? modelData.charAt(0).toUpperCase() + modelData.slice(1) + ": " + Fmt.de(r.power, 0) + " %, " + Fmt.de(r.speed, 0) + " mm/min" : ""
                    }
                }
                LcText {
                    readonly property var best: mc.last && mc.last.result ? mc.last.result.best : null
                    visible: !!best
                    tnum: true
                    text: best ? "Bester Schnitt: " + Fmt.de(best.speed, 0) + " mm/min, " + best.passes + " Durchgänge" : ""
                }
                LcNote {
                    visible: !!mc.last && mc.last.state === "complete" && !!mc.last.saved && mc.last.saved.length > 0
                    Layout.fillWidth: true
                    tone: "ok"
                    text: visible ? "Als Material gespeichert: " + mc.last.saved.map((x) => x.name + " (" + x.process + ")").join(", ") : ""
                }
                LcNote {
                    visible: !!mc.last && (mc.last.state === "error" || mc.last.state === "aborted")
                    Layout.fillWidth: true
                    tone: "bad"
                    text: visible ? (mc.last.error || "Abgebrochen") : ""
                }
            }
        }
    }
}
