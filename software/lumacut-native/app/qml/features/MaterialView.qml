import QtQuick
import QtQuick.Layouts
import LumaCut

// The Pi's material list. Name and thickness make one material; each has up to three processes. The Pi is the source.
Item {
    id: root
    objectName: "view-Material"
    property string query: ""
    property string sel: ""
    readonly property var groups: { Materials.items; return Materials.groups(query) }
    readonly property var all: { Materials.items; return Materials.groups("") }
    readonly property string currentKey: Workspace.hasMaterial ? Materials.groupKey(Workspace.materialName, Workspace.materialThickness) : ""
    // The search only filters the list: the open material stays open while it still exists.
    readonly property var openGroup: {
        for (const g of all) if (g.key === sel) return g
        for (const g of all) if (g.key === currentKey) return g
        return groups.length ? groups[0] : null
    }
    readonly property bool editable: Materials.fromPi
    Component.onCompleted: Materials.load()

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: Theme.surface
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            ColumnLayout {
                anchors.fill: parent
                anchors.rightMargin: 1
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.sp3
                    spacing: Theme.sp1
                    LcInput {
                        objectName: "mt-search"
                        Layout.fillWidth: true
                        icon: "search"
                        placeholder: "Material suchen"
                        onEdited: (t) => root.query = t
                    }
                    LcButton {
                        objectName: "mt-reload"
                        icon: "refresh-cw"; variant: "ghost"
                        tip: "Liste neu laden"
                        onClicked: Materials.load()
                    }
                }
                Flickable {
                    id: list
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentHeight: items.implicitHeight
                    clip: true
                    interactive: false
                    Column {
                        id: items
                        x: Theme.sp2
                        width: list.width - 2 * Theme.sp2
                        Repeater {
                            model: root.groups
                            Rectangle {
                                id: item
                                required property var modelData
                                required property int index
                                readonly property bool on: root.openGroup && root.openGroup.key === modelData.key
                                objectName: "mt-item-" + index
                                width: items.width
                                implicitHeight: itemRow.implicitHeight + 16
                                height: implicitHeight
                                radius: Theme.rMd
                                color: on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
                                property string title: modelData.name
                                RowLayout {
                                    id: itemRow
                                    x: 10; y: 8
                                    width: parent.width - 20
                                    spacing: Theme.sp2
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        LcText { text: item.modelData.name; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                                        LcText { text: Fmt.trim(item.modelData.thicknessMm, 2) + " mm · " + item.modelData.processes; kind: "smallMuted"; tnum: true; Layout.fillWidth: true; elide: Text.ElideRight }
                                    }
                                    LcChip { objectName: "mt-current-chip"; visible: item.modelData.key === root.currentKey; text: "Aktuell"; icon: "check"; tone: "accent" }
                                }
                                MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.sel = item.modelData.key }
                            }
                        }
                    }
                    Column {
                        visible: !root.groups.length
                        anchors.centerIn: parent
                        width: parent.width - 2 * Theme.sp5
                        LcText {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            kind: "muted"
                            text: root.query ? "Nichts gefunden. Anderen Begriff versuchen." : Materials.fromPi ? "Noch kein Material. Lege das erste an." : Materials.loading ? "Liste wird geladen." : "Keine Liste vorhanden. Verbindung zum Pi prüfen."
                        }
                    }
                    WheelHandler { onWheel: (e) => { list.contentY = Math.max(0, Math.min(list.contentHeight - list.height, list.contentY - e.angleDelta.y / 120 * 56)) } }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                LcButton {
                    objectName: "mt-new"
                    Layout.fillWidth: true
                    Layout.margins: Theme.sp3
                    icon: "plus"; text: "Neues Material"
                    enabled: Materials.fromPi
                    onClicked: groupDlg.start(null)
                }
            }
        }
        LcScroll {
            objectName: "mt-detail"
            Layout.fillWidth: true
            Layout.fillHeight: true
            padding: Theme.sp5
            maxContentWidth: 1040
            spacing: Theme.sp3
            LcNote {
                objectName: "mt-offline"
                visible: !Materials.fromPi && !Materials.loading
                Layout.fillWidth: true
                tone: "warn"
                text: "Kein Kontakt zum Pi" + (Materials.error ? ": " + Materials.error : "") + ". Das ist die zuletzt gespeicherte Liste, sie lässt sich nicht ändern."
            }
            Column {
                visible: !root.openGroup
                Layout.fillWidth: true
                Layout.topMargin: 160
                spacing: Theme.sp2
                LcIcon { anchors.horizontalCenter: parent.horizontalCenter; name: "layers-3"; size: 30; width: 30; height: 30; color: Theme.muted }
                LcText { anchors.horizontalCenter: parent.horizontalCenter; text: "Links ein Material wählen oder ein neues anlegen."; kind: "muted" }
            }
            ColumnLayout {
                visible: !!root.openGroup
                Layout.fillWidth: true
                spacing: Theme.sp3
                readonly property bool isCurrent: !!root.openGroup && root.openGroup.key === root.currentKey
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp3
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        LcText { objectName: "mt-title"; text: root.openGroup ? root.openGroup.name : ""; kind: "h1"; Layout.fillWidth: true; elide: Text.ElideRight }
                        LcText { text: root.openGroup ? Fmt.trim(root.openGroup.thicknessMm, 2) + " mm stark" + (root.openGroup.allBuiltin ? " · Startwerte" : "") : ""; kind: "muted"; tnum: true }
                    }
                    LcButton { objectName: "mt-edit"; visible: root.editable; icon: "pencil"; text: "Name und Stärke"; variant: "ghost"; onClicked: groupDlg.start(root.openGroup) }
                    LcButton {
                        objectName: "mt-use"
                        variant: "primary"; size: "lg"; icon: "check"
                        text: parent.parent.isCurrent ? "Wird verwendet" : "Dieses Material verwenden"
                        enabled: root.editable && !parent.parent.isCurrent
                        tip: root.editable ? "" : "Geht nur mit Verbindung zum Pi"
                        onClicked: Materials.use(root.openGroup)
                    }
                }
                RowLayout {
                    visible: parent.isCurrent
                    Layout.fillWidth: true
                    spacing: Theme.sp2
                    LcText { text: "Aufträge rechnen mit dieser Stärke. Die Werte stehen auf den Ebenen im Motiv."; kind: "muted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    LcButton { objectName: "mt-reapply"; size: "sm"; variant: "ghost"; text: "Werte erneut auf die Ebenen"; onClicked: Materials.applyToLayers(root.openGroup) }
                    LcButton { size: "sm"; text: "Weiter zum Motiv"; onClicked: Shell.navigate("motiv") }
                }
                LcNote {
                    objectName: "mt-untested"
                    visible: !!root.openGroup && root.openGroup.anyBuiltin
                    Layout.fillWidth: true
                    tone: "warn"
                    text: "Startwerte sind ungetestet. Erst auf einem Reststück dieses Materials prüfen, zum Beispiel mit dem Materialtest unter Maschine, Kalibrieren."
                }
                ProcessCard { process: "Gravieren"; Layout.fillWidth: true }
                ProcessCard { process: "Markieren"; Layout.fillWidth: true }
                ProcessCard { process: "Schneiden"; Layout.fillWidth: true }
                LcText { text: "Die Werte gelten für alle Geräte. Jedes Material vor dem ersten Auftrag am eigenen Laser auf einem Reststück testen."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
        }
    }

    // Fixed cards, not a repeater: a save reloads the list, and the field you are in must keep the keyboard.
    component ProcessCard: LcCard {
        id: card
        property string process
        readonly property var m: root.openGroup ? Materials.entryOf(root.openGroup, process) : ({})
        readonly property bool has: !!m.id
        readonly property int passes: has ? Materials.effectivePasses(m) : 1
        readonly property var tone: has ? Materials.tonePoints(m) : []
        objectName: "mt-proc-" + process
        spacing: Theme.sp3
        RowLayout {
            visible: !card.has
            Layout.fillWidth: true
            spacing: Theme.sp3
            LcText { text: card.process; kind: "h3" }
            LcText { text: "Für dieses Material noch nicht angelegt. Die Ebene behält dann ihre eigenen Werte."; kind: "muted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            LcButton {
                objectName: "mt-add-" + card.process
                icon: "plus"; text: "Anlegen"; enabled: root.editable
                onClicked: Materials.addProcess(root.openGroup.name, root.openGroup.thicknessMm, card.process)
            }
        }
        RowLayout {
            visible: card.has
            Layout.fillWidth: true
            spacing: Theme.sp2
            LcText { text: card.process; kind: "h3"; Layout.fillWidth: true }
            LcChip { visible: !!card.m.tone_curve; text: "gemessen"; tone: "ok" }
            LcChip { visible: !!card.m.builtin; text: "Startwert" }
            LcSegmented {
                objectName: "mt-mode-" + card.process
                value: card.m.mode || "line"
                enabled: root.editable
                options: [{ value: "line", label: "Linie" }, { value: "fill", label: "Füllen" }]
                onActivated: (v) => Materials.patch(card.m.id, { mode: v })
            }
            LcButton {
                objectName: "mt-del-" + card.process
                visible: !card.m.builtin
                icon: "trash-2"; variant: "ghost"; tip: "Löschen"; enabled: root.editable
                onClicked: Confirm.ask({ title: card.process + " löschen?", body: card.m.name + ", " + Fmt.trim(card.m.thickness_mm, 2) + " mm. Das gilt für alle Geräte.", okLabel: "Löschen", danger: true },
                                       function (yes) { if (yes) Materials.removeEntry(card.m.id) })
            }
        }
        GridLayout {
            visible: card.has
            Layout.fillWidth: true
            columns: Math.max(2, Math.floor(width / 137))
            columnSpacing: Theme.sp3
            rowSpacing: Theme.sp3
            Num { pc: card; label: "Leistung"; key: "power_pct"; name: "power"; min: 8; max: 100; digits: 1; unit: "%" }
            Num { pc: card; label: "Tempo"; key: "speed_mm_min"; name: "speed"; min: 1; max: 30000; step: 50; digits: 0; unit: "mm/min" }
            Num {
                pc: card
                label: "Durchgänge"; key: "passes"; name: "passes"; min: 1; max: 30; digits: 0
                hint: card.m.depth_per_pass_mm > 0 ? "aus Tiefe" : ""
                shown: card.passes
                locked: card.m.depth_per_pass_mm > 0
            }
            Num { pc: card; label: "Zeilenabstand"; key: "interval_mm"; name: "interval"; min: 0.03; max: 2; step: 0.01; digits: 3; unit: "mm" }
            Num { pc: card; label: "Tiefe je Durchgang"; key: "depth_per_pass_mm"; name: "depth"; min: 0; max: 10; step: 0.1; digits: 2; unit: "mm" }
            Num { pc: card; label: "Z-Absenkung"; key: "z_step_mm"; name: "zstep"; min: 0; max: 2; step: 0.1; digits: 2; unit: "mm" }
        }
        LcNote { objectName: "mt-low-" + card.process; visible: card.has && Materials.lowPower(card.m); Layout.fillWidth: true; tone: "warn"; text: "Unter 8 % zündet der Laser nicht sicher." }
        LcNote { visible: card.has && !Materials.focusDropOk(card.passes, card.m.z_step_mm || 0); Layout.fillWidth: true; tone: "warn"; text: "Die Absenkung über alle Durchgänge wird auf 3 mm begrenzt." }
        LcText { visible: card.has && !card.m.tone_curve && card.process === "Gravieren"; text: "Noch keine Tonkurve. Der Materialtest mit Kamera misst sie."; kind: "smallFaint" }
        ColumnLayout {
            objectName: "mt-tone"
            visible: card.has && card.tone.length >= 2
            Layout.fillWidth: true
            spacing: 4
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line; Layout.bottomMargin: Theme.sp2 }
            LcText { text: "Tonkurve: " + card.tone.length + " Messpunkte, von hell nach dunkel mit steigender Energie"; kind: "smallMuted" }
            Canvas {
                id: chart
                Layout.fillWidth: true
                Layout.maximumWidth: 520
                Layout.preferredHeight: 110
                readonly property var pts: card.tone
                readonly property color ink: Theme.accent
                readonly property color warnInk: Theme.warn
                readonly property color axis: Theme.line2
                onPtsChanged: requestPaint()
                onInkChanged: requestPaint()
                onWidthChanged: requestPaint()
                onPaint: {
                    const c = getContext("2d"), P = 8, W = width, H = height
                    c.reset()
                    const px = (v) => P + v * (W - 2 * P), py = (v) => H - P - v * (H - 2 * P)
                    c.strokeStyle = axis; c.lineWidth = 1
                    c.beginPath(); c.moveTo(P, py(0)); c.lineTo(W - P, py(0)); c.stroke()
                    c.strokeStyle = ink; c.lineWidth = 1.5; c.lineJoin = "round"
                    c.beginPath()
                    pts.forEach((p, i) => { if (i) c.lineTo(px(p.x), py(p.y)); else c.moveTo(px(p.x), py(p.y)) })
                    c.stroke()
                    for (const p of pts) {
                        c.fillStyle = p.clean ? ink : warnInk
                        c.beginPath(); c.arc(px(p.x), py(p.y), 3.5, 0, 2 * Math.PI); c.fill()
                    }
                }
            }
        }
    }

    component Num: LcField {
        id: nf
        property var pc
        property string key
        property string name
        property real min: 0
        property real max: 100
        property real step: 1
        property int digits: 2
        property string unit
        property var shown: undefined
        property bool locked: false
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.alignment: Qt.AlignTop
        LcNumber {
            objectName: "mt-" + nf.name + "-" + nf.pc.process
            enabled: root.editable && !nf.locked
            value: nf.shown !== undefined ? nf.shown : (nf.pc.m[nf.key] || 0)
            min: nf.min; max: nf.max; step: nf.step; digits: nf.digits; unit: nf.unit
            onEdited: (v) => { const p = {}; p[nf.key] = v; Materials.patch(nf.pc.m.id, p) }
        }
    }

    // New material with its processes, or new name and thickness for all processes of one.
    LcDialog {
        id: groupDlg
        objectName: "mt-dialog"
        property var edit: null
        property string name: ""
        property real thick: 3
        property var procs: ["Gravieren", "Schneiden"]
        property bool busy: false
        readonly property string clean: name.trim()
        readonly property bool exists: { Materials.items; return Materials.groups("").some((g) => g.name === clean && g.thicknessMm === thick) }
        readonly property bool unchanged: !!edit && clean === edit.name && thick === edit.thicknessMm
        readonly property bool valid: clean.length > 0 && clean.length <= 80 && (edit ? !unchanged : procs.length > 0) && !exists
        function start(group) {
            edit = group
            name = group ? group.name : ""
            thick = group ? group.thicknessMm : 3
            procs = ["Gravieren", "Schneiden"]
            nameField.text = name
            open = true
        }
        function save() {
            busy = true
            const done = function (ok, key) { busy = false; if (ok) { open = false; root.sel = key } }
            if (edit) Materials.renameGroup(edit, clean, thick, done)
            else Materials.createGroup(clean, thick, procs.join(","), done)
        }
        title: edit ? "Name und Stärke" : "Neues Material"
        initialFocus: nameField.input
        onRejected: open = false
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.sp3
            LcField {
                Layout.fillWidth: true
                label: "Material"
                LcInput { id: nameField; objectName: "mt-name"; placeholder: "zum Beispiel Birke"; maxLength: 80; onEdited: (t) => groupDlg.name = t }
            }
            LcField {
                Layout.preferredWidth: 120
                label: "Stärke"
                LcNumber { objectName: "mt-thick"; value: groupDlg.thick; min: 0; max: 60; step: 0.5; digits: 2; unit: "mm"; onEdited: (v) => groupDlg.thick = v }
            }
        }
        LcField {
            visible: !groupDlg.edit
            Layout.fillWidth: true
            label: "Prozesse"
            Row {
                spacing: 14
                height: Theme.hControl
                Repeater {
                    model: ["Gravieren", "Markieren", "Schneiden"]
                    LcCheck {
                        required property string modelData
                        objectName: "mt-proc-check-" + modelData
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                        checked: groupDlg.procs.includes(modelData)
                        onToggled: (on) => { groupDlg.procs = on ? groupDlg.procs.concat([modelData]) : groupDlg.procs.filter((p) => p !== modelData) }
                    }
                }
            }
        }
        LcNote { visible: groupDlg.exists && !groupDlg.unchanged; Layout.fillWidth: true; tone: "warn"; text: "Dieses Material mit dieser Stärke gibt es schon." }
        LcNote { visible: !groupDlg.edit; Layout.fillWidth: true; tone: "warn"; text: "Neue Materialien starten mit groben Werten. Vor dem ersten Auftrag auf einem Reststück testen. Leistung und Tempo gleich danach anpassen." }
        footerLeft: [
            LcButton {
                objectName: "mt-group-delete"
                visible: !!groupDlg.edit && !groupDlg.edit.anyBuiltin
                text: "Material löschen"; variant: "ghost"; textColor: Theme.bad
                onClicked: Confirm.ask({ title: "Material löschen?", body: groupDlg.edit.name + ", " + Fmt.trim(groupDlg.edit.thicknessMm, 2) + " mm mit allen Prozessen. Das gilt für alle Geräte.", okLabel: "Löschen", danger: true },
                                       function (yes) { if (yes) Materials.removeGroup(groupDlg.edit, function (ok) { if (ok) groupDlg.open = false }) })
            }
        ]
        footer: [
            LcButton { objectName: "mt-cancel"; text: "Abbrechen"; onClicked: groupDlg.open = false },
            LcButton { objectName: "mt-save"; variant: "primary"; text: groupDlg.edit ? "Speichern" : "Anlegen"; enabled: groupDlg.valid && !groupDlg.busy; onClicked: groupDlg.save() }
        ]
    }
}
