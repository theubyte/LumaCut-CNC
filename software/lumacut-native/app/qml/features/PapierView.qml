import QtQuick
import QtQuick.Layouts
import LumaCut

// Papier und Karton: gallery of templates (packaging, envelopes, cards, decoration, solids), the form of the chosen one
// and the preview on the sheet. The logic is in Workshop and core/papier; nothing here starts the laser or moves.
Item {
    id: root
    objectName: "view-Papier"
    readonly property var info: Workshop.toolInfo
    readonly property var res: Workshop.result
    readonly property bool narrow: width < 1180
    property string group: ""
    property string query: ""
    readonly property var all: Workshop.tools.filter((t) => t.area === "papier")
    readonly property var groups: [...new Set(all.map((t) => t.group))]
    readonly property var shown: {
        const words = root.query.toLowerCase().split(/\s+/).filter((w) => w.length > 0)
        return root.all.filter((t) => (!root.group || t.group === root.group)
                                      && words.every((w) => (t.title + " " + t.blurb + " " + t.group).toLowerCase().indexOf(w) >= 0))
    }
    Component.onCompleted: if (root.info.area !== "papier") Workshop.tool = AppSettings.value("papier/tool", "faltschachtel") || "faltschachtel"

    // Test handles for the driver.
    function setTool(id) { Workshop.tool = id; return Workshop.tool }
    function setParam(a) { Workshop.setParam(a[0], a[1]); return true }
    function params(_) { return Workshop.params }
    function settle(_) { Workshop.recompute(); return Workshop.result }
    function count(_) { return Document.elementCount }
    function layerNames(_) { return JSON.parse(Document.jsonText()).layers.map((l) => l.name) }
    function layerByName(name) { return JSON.parse(Document.jsonText()).layers.find((l) => l.name === name) || null }
    function reset(_) { Document.reset(); return true }
    function shownIds(_) { return root.shown.map((t) => t.id) }
    function allIds(_) { return root.all.map((t) => t.id) }
    function thumb(id) { return Workshop.thumb(id) }
    function stageState(_) { return { elements: stage.elementCount } }

    // Picture painted on the CPU (Workshop.thumb): no GPU paths, they hung the graphics driver.
    component Thumb: Image {
        id: th
        property string tid
        asynchronous: false
        cache: false
        fillMode: Image.PreserveAspectFit
        smooth: true
        source: "image://papier/" + tid
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- Gallery ----
        Rectangle {
            Layout.preferredWidth: root.narrow ? 290 : 380
            Layout.fillHeight: true
            color: Theme.surface
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            ColumnLayout {
                anchors.fill: parent
                anchors.rightMargin: 1
                spacing: 0
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.sp3
                    spacing: Theme.sp2
                    LcText { text: "Papier und Karton"; kind: "h2" }
                    LcText {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        kind: "smallMuted"
                        text: root.all.length + " Vorlagen zum Schneiden, Falzen und Gravieren. Wählen, anpassen, ins Projekt."
                    }
                    LcInput {
                        objectName: "pp-search"
                        Layout.fillWidth: true
                        icon: "search"
                        placeholder: "Suchen, z. B. Herz, Schachtel, Pop-up"
                        onEdited: (t) => root.query = t
                        Keys.onEscapePressed: { text = ""; root.query = "" }
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 4
                        Repeater {
                            model: [""].concat(root.groups)
                            LcChip {
                                required property var modelData
                                objectName: "pp-group-" + (modelData || "alle")
                                text: modelData || "Alle"
                                clickable: true
                                tone: root.group === modelData ? "accent" : ""
                                onClicked: root.group = modelData
                            }
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                LcScroll {
                    objectName: "pp-gallery"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: Theme.sp2
                    spacing: Theme.sp2
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        rowSpacing: Theme.sp2
                        columnSpacing: Theme.sp2
                        Repeater {
                            model: root.shown
                            Rectangle {
                                id: card
                                required property var modelData
                                readonly property bool on: Workshop.tool === modelData.id
                                objectName: "pp-tpl-" + modelData.id
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                implicitHeight: pic.height + label.implicitHeight + 20
                                radius: Theme.rMd
                                color: on ? Theme.accentSoft : cardArea.containsMouse ? Theme.surface3 : Theme.surface2
                                border.width: 1
                                border.color: on ? Theme.accent : Theme.line
                                Rectangle {
                                    id: pic
                                    x: 6; y: 6
                                    width: card.width - 12
                                    height: Math.round(width * 0.66)
                                    radius: Theme.rSm
                                    color: Theme.sheet
                                    Thumb { anchors.fill: parent; anchors.margins: 4; tid: card.modelData.id }
                                }
                                LcText {
                                    id: label
                                    x: 8
                                    y: pic.y + pic.height + 6
                                    width: card.width - 16
                                    text: card.modelData.title
                                    font.weight: card.on ? Font.DemiBold : Font.Medium
                                    color: card.on ? Theme.accent : Theme.text
                                    elide: Text.ElideRight
                                }
                                MouseArea {
                                    id: cardArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Workshop.tool = card.modelData.id
                                }
                                LcTip { shown: cardArea.containsMouse; text: card.modelData.blurb; side: "right" }
                            }
                        }
                    }
                    LcText { visible: root.shown.length === 0; text: "Keine Vorlage gefunden."; kind: "smallFaint" }
                }
            }
        }

        // ---- Settings ----
        Rectangle {
            Layout.preferredWidth: root.narrow ? Theme.panel : Theme.panelWide
            Layout.fillHeight: true
            color: Theme.bg
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            ColumnLayout {
                anchors.fill: parent
                anchors.rightMargin: 1
                spacing: 0
                LcScroll {
                    objectName: "pp-form-scroll"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: Theme.sp4
                    spacing: Theme.sp3
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        LcText { objectName: "pp-heading"; text: root.info.area === "papier" ? (root.info.title || "") : ""; kind: "h2"; Layout.fillWidth: true; elide: Text.ElideRight }
                        LcText { text: root.info.blurb || ""; kind: "muted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                    WsForm { Layout.fillWidth: true; visible: root.info.area === "papier" }
                    LcNote {
                        objectName: "pp-error"
                        visible: !!root.res.error
                        Layout.fillWidth: true
                        tone: "bad"
                        text: root.res.error || ""
                    }
                    Repeater {
                        model: !root.res.error ? (root.res.warnings || []) : []
                        LcNote { required property var modelData; Layout.fillWidth: true; tone: "warn"; text: modelData }
                    }
                    Repeater {
                        model: !root.res.error ? (root.res.notes || []) : []
                        LcText { required property var modelData; Layout.fillWidth: true; kind: "smallMuted"; wrapMode: Text.WordWrap; text: modelData }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.sp3
                    spacing: Theme.sp2
                    LcButton {
                        objectName: "pp-reset"
                        icon: "undo-2"; variant: "ghost"
                        tip: "Werte zurücksetzen"
                        onClicked: Workshop.resetParams()
                    }
                    Item { Layout.fillWidth: true }
                    LcButton {
                        objectName: "pp-to-motiv"
                        icon: "pencil"; variant: "ghost"
                        tip: "Zum Motiv: dort liegen die übernommenen Teile"
                        onClicked: Shell.navigate("motiv")
                    }
                    LcButton {
                        objectName: "pp-apply"
                        variant: "primary"
                        icon: "plus"; text: "Ins Projekt"
                        lock: root.res.ok ? "" : (root.res.error || "Nichts zum Übernehmen")
                        tip: "Legt die Teile auf eine freie Platte, je Bogen eine. Gelasert wird erst unter Starten mit Go."
                        onClicked: Workshop.apply()
                    }
                }
            }
        }

        // ---- Preview ----
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Stage {
                id: stage
                objectName: "pp-stage"
                anchors.fill: parent
                interactive: true
                canvasColor: "transparent"
                sheetColor: Theme.sheet
                gridColor: Theme.grid
                gridMajorColor: Theme.gridMajor
                edgeColor: Theme.line2
                parkColor: Theme.park
                selectionColor: Theme.accent
                Component.onCompleted: Workshop.attachPreview(stage)
                onWidthChanged: Workshop.fitPreview()
                onHeightChanged: Workshop.fitPreview()
            }
            RowLayout {
                visible: root.res.ok === true
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: Theme.sp3
                spacing: Theme.sp2
                LcChip { objectName: "pp-size"; text: root.res.size || ""; icon: "ruler" }
                LcChip { text: (root.res.plates || 0) > 1 ? root.res.plates + " Bögen" : "1 Bogen" }
                LcSegmented {
                    objectName: "pp-preview-plate"
                    visible: (root.res.plates || 0) > 1
                    value: Workshop.previewPlate
                    options: { const o = []; for (let i = 0; i < (root.res.plates || 0); ++i) o.push({ value: i, label: "Bogen " + (i + 1) }); return o }
                    onActivated: (v) => Workshop.previewPlate = v
                }
            }
            LcButton {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.sp3
                icon: "maximize-2"; variant: "ghost"
                tip: "Vorschau einpassen"
                onClicked: Workshop.fitPreview()
            }
            Row {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: Theme.sp3
                spacing: Theme.sp3
                Repeater {
                    model: [{ c: "#FF6B70", t: "Schneiden" }, { c: "#FFB45C", t: "Falzen" }, { c: "#6CB6FF", t: "Markieren" }, { c: "#3FBF9F", t: "Gravieren" }, { c: "#8A93A8", t: "Bogen" }]
                    Row {
                        required property var modelData
                        spacing: 5
                        Rectangle { width: 14; height: 3; radius: 1.5; color: parent.modelData.c; anchors.verticalCenter: parent.verticalCenter }
                        LcText { text: parent.modelData.t; kind: "smallFaint" }
                    }
                }
            }
        }
    }
}
