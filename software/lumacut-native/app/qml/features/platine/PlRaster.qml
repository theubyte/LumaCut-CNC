import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import LumaCut

// Lochraster mode: parts left, the board in the middle (edit with the mouse), settings, checks and assembly right.
// All logic is in the Perfboard singleton. The laser only marks the solder mask here; nothing is cut.
Item {
    id: rr
    // Parts list filtered by the search line: every word must appear in name, value, category or id.
    readonly property var libFound: {
        const words = libSearch.text.toLowerCase().split(/\s+/).filter(w => w.length > 0)
        if (words.length === 0) return Perfboard.library
        return Perfboard.library.filter(p => {
            const hay = (p.name + " " + p.value + " " + p.category + " " + p.id).toLowerCase()
            return words.every(w => hay.indexOf(w) >= 0)
        })
    }

    // Test handle: what a native file dialog or a hand on the mouse is not needed for.
    Item {
        objectName: "lochraster-api"
        function info(_) { return Perfboard.info() }
        function newDesign(i) { Perfboard.newDesign(i); return Perfboard.info() }
        function openTemplate(id) { Perfboard.openTemplate(id); return Perfboard.info() }
        function place(a) { return Perfboard.placePart(a[0], a[1], a[2], a[3] || 0) }
        function wire(a) { Perfboard.addWire(a[0], a[1], a[2], a[3], a[4], a[5] || false); return Perfboard.info().wires }
        function label(a) { Perfboard.addLabel(a[0], a[1], a[2]); return Perfboard.info().labels }
        function selectRef(r) { Perfboard.selectRef(r); return Perfboard.selection }
        function selection(_) { return Perfboard.selection }
        function setSel(a) { Perfboard.setSelValue(a[0], a[1]); return Perfboard.selection }
        function checks(_) { return Perfboard.checks }
        function bom(_) { return Perfboard.bomRows }
        function options(_) { return Perfboard.options }
        function setOption(a) { Perfboard.setOption(a[0], a[1]); return Perfboard.options }
        function holeWin(a) { const p = stage.mapToItem(null, stage.holeItemPos(a[0], a[1])); return [p.x, p.y] }
        function save(p) { return Perfboard.save(p) }
        function open(p) { return Perfboard.open(p) }
        function exportTo(a) { return Perfboard.exportTo(a[0], a[1]) }
        function toProject(_) { Perfboard.toProject(); return true }
        function bed(_) { return [Perfboard.bedX, Perfboard.bedY] }
        function shown(_) { return stage.shownElements }
        function undo(_) { Perfboard.undo(); return Perfboard.info() }
    }

    Connections {
        target: Perfboard
        function onFileRequested(what) {
            fileDlg.what = what
            if (what === "open") {
                fileDlg.fileMode = FileDialog.OpenFile
                fileDlg.nameFilters = ["Lochraster-Entwurf (*.lumaraster)"]
            } else {
                const ext = what === "save" ? "lumaraster" : what
                fileDlg.fileMode = FileDialog.SaveFile
                fileDlg.nameFilters = [what === "save" ? "Lochraster-Entwurf (*.lumaraster)" : what === "csv" ? "Stückliste (*.csv)" : what.toUpperCase() + " (*." + what + ")"]
                fileDlg.currentFile = "file:///" + Perfboard.suggestedName(ext)
            }
            fileDlg.open()
        }
    }
    FileDialog {
        id: fileDlg
        property string what: "open"
        title: what === "open" ? "Lochraster öffnen" : what === "save" ? "Lochraster speichern" : "Exportieren"
        onAccepted: {
            const f = selectedFile.toString()
            if (what === "open") Perfboard.open(f)
            else if (what === "save") Perfboard.save(f)
            else Perfboard.exportTo(f, what)
        }
    }
    LcMenu {
        id: exportMenu
        objectName: "pf-export-menu"
        items: [{ label: "Bestückungsplan als PNG", icon: "image", action: function() { Perfboard.askExport("png") } },
                { label: "Bestückungsplan als SVG", icon: "download", action: function() { Perfboard.askExport("svg") } },
                { label: "Stückliste als CSV", icon: "download", action: function() { Perfboard.askExport("csv") } }]
    }
    LcMenu {
        id: newMenu
        objectName: "pf-new-menu"
        items: Perfboard.templates.map(t => ({ label: "Neu: " + t.label + " mm", action: function() { Perfboard.newDesign(t.value) } }))
               .concat([{ separator: true }])
               .concat(Perfboard.designTemplates.map(t => ({ label: "Vorlage öffnen: " + t.name, icon: "circuit-board", action: function() { Perfboard.openTemplate(t.id) } })))
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- Left: tools and parts ----
        Rectangle {
            Layout.fillHeight: true
            // Narrow windows (1024 wide) keep the board usable: the side panels give way first.
            Layout.preferredWidth: Math.round(Math.min(Theme.panel, Math.max(200, rr.width * 0.22)))
            color: Theme.surface
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            LcScroll {
                anchors.fill: parent
                anchors.rightMargin: 1
                spacing: Theme.sp3
                LcText { text: "Bauteile"; kind: "section" }
                LcText { text: "Bauteil wählen, dann auf das Loch für Pin 1 klicken. R dreht."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                LcInput {
                    id: libSearch
                    objectName: "pf-lib-search"
                    Layout.fillWidth: true
                    icon: "search"
                    placeholder: "Suchen, z. B. ESP, DIP, Elko"
                    Keys.onEscapePressed: { text = ""; stage.forceActiveFocus() }
                }
                LcText {
                    visible: rr.libFound.length === 0
                    text: "Kein Bauteil gefunden."
                    kind: "smallFaint"
                }
                Repeater {
                    model: [...new Set(rr.libFound.map(p => p.category))]
                    ColumnLayout {
                        id: cat
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 2
                        LcText { text: cat.modelData; kind: "smallMuted"; font.weight: Font.DemiBold; Layout.topMargin: Theme.sp1 }
                        Repeater {
                            model: rr.libFound.filter(p => p.category === cat.modelData)
                            Rectangle {
                                id: libRow
                                required property var modelData
                                readonly property bool on: Perfboard.tool === "part" && Perfboard.partId === modelData.id
                                objectName: "pf-lib-" + modelData.id
                                Layout.fillWidth: true
                                height: Theme.hControl - 2
                                radius: Theme.rSm
                                color: on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
                                LcText {
                                    anchors.left: parent.left; anchors.leftMargin: Theme.sp2
                                    anchors.right: pinsText.left; anchors.rightMargin: Theme.sp2
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: libRow.modelData.name
                                    color: libRow.on ? Theme.accent : Theme.text
                                    elide: Text.ElideRight
                                }
                                LcText { id: pinsText; anchors.right: parent.right; anchors.rightMargin: Theme.sp2; anchors.verticalCenter: parent.verticalCenter; text: libRow.modelData.pins + " Pins"; kind: "smallFaint" }
                                MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { Perfboard.pickPart(libRow.modelData.id); stage.forceActiveFocus() } }
                                LcTip { shown: area.containsMouse && libRow.modelData.hint.length > 0; text: libRow.modelData.hint; side: "right" }
                            }
                        }
                    }
                }
            }
        }

        // ---- Middle: toolbar and board ----
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            spacing: 0
            Rectangle {
                id: toolbar
                readonly property bool compact: width < 560
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.mvBar
                color: Theme.surface
                clip: true
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.sp3
                    anchors.rightMargin: Theme.sp3
                    spacing: Theme.sp2
                    LcButton { id: newBtn; objectName: "pf-new"; size: "sm"; variant: "ghost"; icon: "plus"; tip: "Neuer Entwurf oder Vorlage öffnen"; onClicked: newMenu.openAt(newBtn) }
                    LcButton { objectName: "pf-open"; size: "sm"; variant: "ghost"; icon: "folder-open"; tip: "Öffnen (.lumaraster)"; onClicked: Perfboard.askOpen() }
                    LcButton { objectName: "pf-save"; size: "sm"; variant: "ghost"; icon: "save"; tip: "Speichern (.lumaraster)"; onClicked: Perfboard.askSave() }
                    LcButton { id: expBtn; objectName: "pf-export"; size: "sm"; variant: "ghost"; icon: "download"; tip: "Bestückungsplan und Stückliste exportieren"; onClicked: exportMenu.openAt(expBtn) }
                    Rectangle { width: 1; height: 18; color: Theme.line }
                    LcButton { objectName: "pf-undo"; size: "sm"; variant: "ghost"; icon: "undo-2"; tip: "Rückgängig (Strg+Z)"; enabled: Perfboard.canUndo; onClicked: Perfboard.undo() }
                    LcButton { objectName: "pf-redo"; size: "sm"; variant: "ghost"; icon: "redo-2"; tip: "Wiederholen (Strg+Y)"; enabled: Perfboard.canRedo; onClicked: Perfboard.redo() }
                    Rectangle { width: 1; height: 18; color: Theme.line }
                    LcSegmented {
                        objectName: "pf-tool"
                        options: [{ value: "select", label: toolbar.compact ? "" : "Auswählen", icon: "mouse-pointer-2", tip: "Auswählen (V)" },
                                  { value: "wire", label: toolbar.compact ? "" : "Verbindung", icon: "spline", tip: "Verbindung (W)" },
                                  { value: "text", label: toolbar.compact ? "" : "Text", icon: "type", tip: "Text (T)" }]
                        value: Perfboard.tool === "part" ? "select" : Perfboard.tool
                        onActivated: (v) => { Perfboard.tool = v; stage.forceActiveFocus() }
                    }
                    Item { Layout.fillWidth: true }
                }
            }
            Rectangle {
                id: canvas
                objectName: "pf-canvas"
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.canvas
                clip: true
                PerfboardStage {
                    id: stage
                    objectName: "pf-stage"
                    anchors.fill: parent
                    anchors.margins: Theme.sp3
                    canvasColor: "transparent"
                    sheetColor: Theme.canvas
                    edgeColor: "transparent"
                    boardColor: Theme.pcbPerf
                    padColor: Theme.pcbTin
                    holeColor: Theme.pcbDrill
                    bodyColor: Theme.pcbSilk
                    solderColor: Theme.pcbCopper
                    wireColor: Theme.info
                    laserColor: Theme.pcbLaser
                    accentColor: Theme.accent
                    warnColor: Theme.warn
                    focus: true
                    lineWidth: 1.6
                }
                // References on the parts, placed from the stage; they move with zoom and view.
                Repeater {
                    model: stage.effectiveZoom > 3.5 ? Perfboard.parts : []
                    LcText {
                        required property var modelData
                        readonly property point p: { stage.viewRevision; return stage.boardToItem(modelData.x, modelData.y) }
                        x: stage.x + p.x - width / 2
                        y: stage.y + p.y - height / 2
                        text: modelData.ref
                        font.pixelSize: Theme.fsXs
                        font.weight: Font.DemiBold
                        color: Theme.text
                        style: Text.Outline
                        styleColor: Theme.surface
                    }
                }
                Row {
                    anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: Theme.sp4
                    spacing: Theme.sp3
                    LcSegmented {
                        objectName: "pf-view"
                        options: [{ value: false, label: "Von oben" }, { value: true, label: "Von unten", tip: "Lötseite, gespiegelt" }]
                        value: Perfboard.viewBelow
                        onActivated: (v) => Perfboard.viewBelow = v
                    }
                    Rectangle {
                        width: marksCheck.implicitWidth + 2 * Theme.sp3; height: Theme.hControl; radius: Theme.rMd
                        color: Theme.surface; border.width: 1; border.color: Theme.line
                        LcCheck { id: marksCheck; objectName: "pf-marks"; anchors.centerIn: parent; text: canvas.width < 520 ? "Markierung" : "Laser-Markierung zeigen"; checked: Perfboard.showMarks; onToggled: (on) => Perfboard.showMarks = on }
                    }
                }
                Row {
                    id: topRow
                    x: Theme.sp4; y: Theme.sp4
                    spacing: Theme.sp2
                    LcSegmented {
                        objectName: "pf-wireside"
                        visible: Perfboard.tool === "wire"
                        options: [{ value: true, label: "Lötseite", tip: "Lötbrücke unten" }, { value: false, label: "Bestückungsseite", tip: "Drahtbrücke oben" }]
                        value: Perfboard.wireSolder
                        onActivated: (v) => Perfboard.wireSolder = v
                    }
                    LcChip { objectName: "pf-view-chip"; visible: canvas.width >= 760 && Perfboard.tool !== "wire"; icon: "eye"; text: Perfboard.viewBelow ? "Von unten: Lötseite, gespiegelt" : "Von oben: Bestückungsseite" }
                    LcChip { visible: canvas.width >= 420 && Perfboard.tool !== "wire"; text: canvas.width >= 600 ? Perfboard.board.size + ", " + Perfboard.board.grid : Perfboard.board.size }
                }
                LcButton {
                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Theme.sp4
                    size: "sm"; icon: "maximize"; tip: "Ganze Platine zeigen"
                    onClicked: stage.fitBoard()
                }
                Rectangle {
                    objectName: "pf-hint"
                    visible: Perfboard.hint.length > 0
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: Theme.sp4 + Theme.hControl + Theme.sp2
                    width: Math.min(hintText.implicitWidth + 2 * Theme.sp3, parent.width - 2 * Theme.sp5)
                    height: hintText.height + 2 * Theme.sp1 + 2
                    radius: Theme.rMd
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.line
                    LcText { id: hintText; anchors.centerIn: parent; width: Math.min(implicitWidth, parent.parent.width - 2 * Theme.sp5 - 2 * Theme.sp3); text: Perfboard.hint; kind: "smallMuted"; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter }
                }
            }
        }

        PlRasterSide {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(Math.max(300, Math.min(rr.width * 0.3, Theme.panelWide)))
        }
    }
}
