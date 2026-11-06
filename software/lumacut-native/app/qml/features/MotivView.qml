import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import LumaCut

// The design editor: toolbar on top, tools left, stage in the middle, layers and properties right, plates below.
// All logic is in Editor and MotivStage; this only arranges and shows.
Item {
    id: root
    objectName: "view-Motiv"

    // Test handles for the driver.
    function win(p) { const q = stage.mapToItem(null, stage.mmToItem(Qt.point(p[0], p[1]))); return [q.x, q.y] }
    function itemToWin(p) { const q = stage.mapToItem(null, p); return [q.x, q.y] }
    function handle(name) { const q = stage.mapToItem(null, stage.handleItemPos(name)); return [q.x, q.y] }
    function node(n) { const q = stage.mapToItem(null, stage.nodeItemPos(n[0], n[1])); return [q.x, q.y] }
    function element(i) { return Editor.elementInfo(i) }
    function count(_) { return Document.elementCount }
    function selection(_) { return Editor.sel }
    function stress(n) { return Editor.stress(n) }
    function sample(_) { Editor.sample(); return true }
    function reset(_) { Document.reset(); return true }
    function selectAll(_) { Editor.selectAll(); return Document.selectionCount }
    function undo(_) { Document.undo(); return Document.undoDepth }
    function stageState(_) { return { loading: stage.loading, elements: stage.elementCount, instances: stage.instanceCount, pending: stage.pendingUpload, dragMs: stage.dragMs, moved: stage.scanCount, zoom: stage.effectiveZoom } }
    function layerIds(_) { return Editor.layerIds }
    function layerRow(id) { return Editor.layerRow(id) }
    function setTool(t) { Editor.tool = t; return t }
    function dirty(_) { return Document.dirty }
    function title(_) { return Shell.projectTitle }
    function exportTo(a) { Editor.exportTo(a[0], a[1]); return true }
    function importFile(path) { Editor.importPath(path); return true }
    function frame(_) { return stage.frameInfo() }
    function toJson(_) { return Document.jsonText() }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        MvToolbar {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.mvBar
            stage: stage
            z: 5
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0
            MvTools { Layout.preferredWidth: Theme.mvTools; Layout.fillHeight: true }
            Rectangle {
                id: canvas
                objectName: "mv-canvas"
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.canvas
                clip: true

                RulerItem {
                    id: rulerTop
                    x: Theme.ruler; y: 0
                    width: parent.width - Theme.ruler; height: Theme.ruler
                    zoom: stage.effectiveZoom; pan: stage.pan.x
                    hasSel: Editor.sel.hasBox === true
                    selFrom: Editor.sel.x || 0; selTo: (Editor.sel.x || 0) + (Editor.sel.boxW || 0)
                    tickColor: Theme.faint; textColor: Theme.muted; bandColor: Theme.accentSoft
                    font.family: Theme.font; font.pixelSize: Theme.fsXs - 1
                    z: 3
                }
                RulerItem {
                    id: rulerLeft
                    vertical: true
                    x: 0; y: Theme.ruler
                    width: Theme.ruler; height: parent.height - Theme.ruler
                    zoom: stage.effectiveZoom; pan: stage.pan.y
                    hasSel: Editor.sel.hasBox === true
                    selFrom: Editor.sel.y || 0; selTo: (Editor.sel.y || 0) + (Editor.sel.boxH || 0)
                    tickColor: Theme.faint; textColor: Theme.muted; bandColor: Theme.accentSoft
                    font.family: Theme.font; font.pixelSize: Theme.fsXs - 1
                    z: 3
                }
                Rectangle { z: 2; x: 0; y: 0; width: parent.width; height: Theme.ruler - 1; color: Theme.surface }
                Rectangle { z: 2; x: 0; y: 0; width: Theme.ruler - 1; height: parent.height; color: Theme.surface }
                Rectangle { z: 3; x: 0; y: Theme.ruler - 1; width: parent.width; height: 1; color: Theme.line }
                Rectangle { z: 3; x: Theme.ruler - 1; y: 0; width: 1; height: parent.height; color: Theme.line }
                Rectangle { z: 4; x: 0; y: 0; width: Theme.ruler - 1; height: Theme.ruler - 1; color: Theme.surface
                    LcText { anchors.centerIn: parent; text: "mm"; kind: "smallFaint"; font.pixelSize: Theme.fsXs - 1 }
                }
                Rectangle { z: 4; visible: stage.mouseInside; x: Theme.ruler + Math.round(stage.mouseItem.x); y: 0; width: 1; height: Theme.ruler - 1; color: Theme.accent }
                Rectangle { z: 4; visible: stage.mouseInside; x: 0; y: Theme.ruler + Math.round(stage.mouseItem.y); width: Theme.ruler - 1; height: 1; color: Theme.accent }

                Item {
                    id: stageBox
                    x: Theme.ruler; y: Theme.ruler
                    width: parent.width - Theme.ruler
                    height: parent.height - Theme.ruler
                    clip: true

                    readonly property real zoom: stage.effectiveZoom
                    readonly property real sheetX: stage.pan.x
                    readonly property real sheetY: stage.pan.y
                    readonly property real sheetW: Editor.bedW * zoom
                    readonly property real sheetH: Editor.bedH * zoom

                    // The sheet casts a soft shadow, so it reads as the machine's bed lying on the desk.
                    RectangularShadow {
                        x: stageBox.sheetX; y: stageBox.sheetY
                        width: stageBox.sheetW; height: stageBox.sheetH
                        offset.y: 2
                        blur: 16
                        color: Theme.shadowSoft
                    }
                    MotivStage {
                        id: stage
                        objectName: "stage"
                        anchors.fill: parent
                        canvasColor: "transparent"
                        sheetColor: Theme.sheet
                        gridColor: Theme.grid
                        gridMajorColor: Theme.gridMajor
                        edgeColor: Theme.line2
                        parkColor: Theme.park
                        selectionColor: Theme.accent
                        accentColor: Theme.accent
                        accentSoftColor: Theme.accentSoft
                        surfaceColor: Theme.surface
                        badColor: Theme.bad
                        warnColor: Theme.warn
                        onContextMenuRequested: (x, y) => ctx.show(x, y)
                        onFileKey: (a) => files.run(a)
                    }
                    // Label of the park corner or locked strip.
                    LcText {
                        visible: stageBox.zoom * Editor.parkW > 76 && stageBox.zoom * Editor.parkH > 20
                        x: stageBox.sheetX + Editor.parkX * stageBox.zoom + (Editor.parkW * stageBox.zoom - width) / 2
                        y: stageBox.sheetY + (Editor.parkH * stageBox.zoom - height) / 2
                        text: Editor.parkName
                        color: Theme.bad
                        font.pixelSize: Theme.fsXs
                        font.weight: Font.Medium
                    }
                    LcText {
                        objectName: "bed-label"
                        x: stageBox.sheetX
                        y: stageBox.sheetY + stageBox.sheetH + Theme.sp2
                        text: Editor.bedLabel
                        kind: "smallFaint"
                        font.pixelSize: Theme.fsXs
                    }
                    // Warnings sit on the object.
                    Repeater {
                        model: Editor.warnings
                        MvPill {
                            required property var modelData
                            objectName: "warn-" + modelData.kind
                            text: modelData.text
                            tone: modelData.kind === 1 ? "bad" : "warn"
                            x: Math.round(Math.max(4, Math.min(stageBox.sheetX + modelData.minX * stageBox.zoom - 3, stageBox.width - width - 4)))
                            y: Math.round(Math.min(stageBox.sheetY + modelData.maxY * stageBox.zoom + 10, stageBox.height - height - 4))
                        }
                    }
                    MvPill {
                        objectName: "stage-pill"
                        visible: stage.pillText.length > 0
                        text: stage.pillText
                        tone: "accent"
                        x: Math.round(Math.max(4, Math.min(stage.pillX, stageBox.width - width - 4)))
                        y: Math.round(Math.min(stage.pillY, stageBox.height - height - 4))
                    }
                    // Tool hint
                    Rectangle {
                        objectName: "tool-hint"
                        visible: Editor.hint.length > 0
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: Theme.sp3
                        width: Math.min(hintText.implicitWidth + 2 * Theme.sp3, parent.width - 2 * Theme.sp5)
                        height: hintText.implicitHeight + 2 * Theme.sp1 + 2
                        radius: Theme.rMd
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.line
                        LcText {
                            id: hintText
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.leftMargin: Theme.sp3; anchors.rightMargin: Theme.sp3
                            anchors.verticalCenter: parent.verticalCenter
                            text: Editor.hint
                            kind: "smallMuted"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                    // Invitation when the plate is empty
                    Rectangle {
                        id: empty
                        objectName: "empty-state"
                        visible: Editor.plateEmpty && Editor.tool === "select"
                        anchors.centerIn: parent
                        width: emptyCol.implicitWidth + 2 * Theme.sp6
                        height: emptyCol.implicitHeight + 2 * Theme.sp5
                        radius: Theme.rXl
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.line
                        layer.enabled: false
                        ColumnLayout {
                            id: emptyCol
                            anchors.centerIn: parent
                            spacing: Theme.sp2
                            LcText {
                                Layout.alignment: Qt.AlignHCenter
                                text: Document.activePlate > 0 ? "Platte " + (Document.activePlate + 1) + " ist noch leer" : "Was soll auf die Platte?"
                                kind: "h2"
                            }
                            LcText {
                                Layout.alignment: Qt.AlignHCenter
                                text: "Eine Form zeichnen, eine Datei hierher ziehen oder mit einer Vorlage beginnen."
                                kind: "muted"
                            }
                            RowLayout {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.topMargin: Theme.sp2
                                spacing: Theme.sp2
                                LcButton { objectName: "empty-rect"; icon: "rectangle-horizontal"; text: "Form zeichnen"; onClicked: Editor.tool = "rect" }
                                LcButton { objectName: "empty-import"; icon: "file-up"; text: "Datei öffnen"; onClicked: Editor.askImport() }
                                LcButton { objectName: "empty-template"; icon: "shapes"; text: "Vorlage aus der Werkstatt"; onClicked: Shell.navigate("werkstatt") }
                            }
                        }
                    }
                    RectangularShadow {
                        z: -1
                        visible: empty.visible
                        anchors.fill: empty
                        radius: empty.radius
                        offset.y: 6
                        blur: 28
                        color: Theme.shadowSoft
                    }
                    Rectangle {
                        objectName: "mv-busy"
                        visible: Editor.busy
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: Theme.sp4
                        width: busyRow.implicitWidth + 2 * Theme.sp3
                        height: Theme.hControl
                        radius: Theme.rMd
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.line
                        Row {
                            id: busyRow
                            anchors.centerIn: parent
                            spacing: Theme.sp2
                            LcSpinner { size: 12; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                            LcText { text: Editor.busyText; kind: "smallMuted"; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                    DropArea {
                        id: drop
                        anchors.fill: parent
                        onDropped: (d) => {
                            const list = []
                            for (const u of d.urls) list.push(u.toString())
                            if (list.length) Editor.importPaths(list)
                        }
                    }
                    Rectangle {
                        visible: drop.containsDrag
                        anchors.fill: parent
                        anchors.margins: Theme.sp6
                        radius: Theme.rLg
                        color: Theme.accentSoft
                        border.width: 2
                        border.color: Theme.accent
                        Column {
                            anchors.centerIn: parent
                            spacing: Theme.sp2
                            LcIcon { anchors.horizontalCenter: parent.horizontalCenter; name: "file-up"; size: 22; width: 22; height: 22; color: Theme.accent }
                            LcText { text: "Datei hier ablegen"; color: Theme.accent; font.weight: Font.DemiBold }
                        }
                    }
                }
            }
            Rectangle {
                objectName: "mv-side"
                Layout.preferredWidth: Theme.mvSide
                Layout.fillHeight: true
                color: Theme.surface
                Rectangle { width: 1; height: parent.height; color: Theme.line }
                Flickable {
                    id: sideFlick
                    objectName: "mv-side-scroll"
                    anchors.fill: parent
                    anchors.leftMargin: 1
                    contentWidth: width
                    contentHeight: sideProps.y + sideProps.height
                    interactive: false
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    MvLayers { id: sideLayers; width: sideFlick.width; height: implicitHeight }
                    Rectangle { y: sideLayers.height; width: sideFlick.width; height: 1; color: Theme.line }
                    MvProps { id: sideProps; y: sideLayers.height + 1; width: sideFlick.width; height: implicitHeight }
                    ScrollBar.vertical: LcScrollBar {}
                    WheelHandler {
                        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                        onWheel: (e) => { sideFlick.contentY = Math.max(0, Math.min(sideFlick.contentHeight - sideFlick.height, sideFlick.contentY - e.angleDelta.y / 120 * 64)) }
                    }
                }
            }
        }
        MvPlateBar { Layout.fillWidth: true; Layout.preferredHeight: Theme.mvPlates; z: 5 }
    }

    MvFiles { id: files }
    MvDialogs { files: files }

    LcMenu {
        id: ctx
        objectName: "mv-context"
        function show(x, y) {
            const s = Editor.sel
            let list = []
            if (!s.count) {
                list = [
                    { label: "Einfügen", icon: "clipboard-paste", kbd: "Strg+V", disabled: !Editor.hasClipboard, action: () => Editor.paste() },
                    { label: "Alles auswählen", kbd: "Strg+A", disabled: Editor.plateEmpty, action: () => Editor.selectAll() },
                    { separator: true },
                    { label: "Arbeitsfläche einpassen", kbd: "F", action: () => stage.fitBed() }
                ]
            } else {
                list = [
                    { label: "Ausschneiden", icon: "scissors", kbd: "Strg+X", action: () => Editor.cutSel() },
                    { label: "Kopieren", icon: "copy", kbd: "Strg+C", action: () => Editor.copySel() },
                    { label: "Einfügen", icon: "clipboard-paste", kbd: "Strg+V", disabled: !Editor.hasClipboard, action: () => Editor.paste() },
                    { label: "Duplizieren", icon: "copy-plus", kbd: "Strg+D", action: () => Editor.duplicate() },
                    { separator: true },
                    { label: "Gruppieren", icon: "group", kbd: "Strg+G", disabled: s.count < 2, action: () => Editor.group() },
                    { label: "Gruppe auflösen", icon: "ungroup", kbd: "Strg+Umschalt+G", disabled: !s.anyGroup, action: () => Editor.ungroup() },
                    { label: "Aufteilen", icon: "split", disabled: !s.canSplit, action: () => Editor.splitSel() },
                    { separator: true },
                    { label: "Links und rechts spiegeln", icon: "flip-horizontal-2", action: () => Editor.mirror(true) },
                    { label: "Oben und unten spiegeln", icon: "flip-vertical-2", action: () => Editor.mirror(false) },
                    { label: "Nach vorn", icon: "bring-to-front", action: () => Editor.toFront(true) },
                    { label: "Nach hinten", icon: "send-to-back", action: () => Editor.toFront(false) }
                ]
                if (s.vectors >= 2) list.push({ separator: true },
                    { label: "Verschweißen", icon: "squares-unite", action: () => Editor.booleanSel("union") },
                    { label: "Abziehen", icon: "squares-subtract", action: () => Editor.booleanSel("subtract") },
                    { label: "Schnittmenge", icon: "squares-intersect", action: () => Editor.booleanSel("intersect") })
                list.push({ separator: true }, { label: "Kontur erzeugen …", icon: "square-dashed", action: () => Editor.dialog = "contour" })
                if (s.anyImage) list.push({ label: "Vektorisieren …", icon: "image-off", action: () => Editor.dialog = "vectorize" })
                if (s.anyText) list.push({ label: "In Pfade umwandeln", icon: "type", action: () => Editor.textToPaths() })
                const layers = Editor.layerMenu()
                if (layers.length) {
                    list.push({ separator: true })
                    for (const l of layers) list.push({ label: "Auf Ebene " + l.label, action: () => Editor.moveSelectionToLayer(l.id) })
                }
                list.push({ separator: true }, { label: "Löschen", icon: "trash-2", kbd: "Entf", action: () => Editor.deleteSel() })
            }
            items = list
            popup(x, y)
        }
    }
}
