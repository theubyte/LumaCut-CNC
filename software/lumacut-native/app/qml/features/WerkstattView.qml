import QtQuick
import QtQuick.Layouts
import LumaCut

// Generators that put parts into the open project. All logic is in Workshop; nothing here starts the laser or moves.
Item {
    id: root
    objectName: "view-Werkstatt"
    readonly property var info: Workshop.toolInfo
    readonly property var res: Workshop.result
    readonly property bool computes: !!info.compute
    readonly property bool narrow: width < 1100

    // Test handles for the driver.
    function setTool(id) { Workshop.tool = id; return Workshop.tool }
    function setParam(a) { Workshop.setParam(a[0], a[1]); return true }
    function params(_) { return Workshop.params }
    function settle(_) { Workshop.recompute(); return Workshop.result }
    function result(_) { return Workshop.result }
    function count(_) { return Document.elementCount }
    function plates(_) { return { count: Document.plateCount, active: Document.activePlate } }
    function layerNames(_) { return JSON.parse(Document.jsonText()).layers.map((l) => l.name) }
    function elementNames(_) { return JSON.parse(Document.jsonText()).elements.map((e) => e.kind) }
    function stageState(_) { return { loading: stage.loading, elements: stage.elementCount, zoom: stage.effectiveZoom } }
    function reset(_) { Document.reset(); return true }
    function layerByName(name) { return JSON.parse(Document.jsonText()).layers.find((l) => l.name === name) || null }
    function setting(key) { return AppSettings.value(key, null) }
    function undo(_) { Document.undo(); return Document.elementCount }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- Generators ----
        Rectangle {
            Layout.preferredWidth: Theme.wsList
            Layout.fillHeight: true
            color: Theme.surface
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            LcScroll {
                anchors.fill: parent
                anchors.rightMargin: 1
                padding: Theme.sp2
                spacing: 2
                LcText { text: "Werkstatt"; kind: "h2"; Layout.leftMargin: Theme.sp2; Layout.topMargin: Theme.sp2; Layout.bottomMargin: Theme.sp1 }
                Repeater {
                    model: Workshop.tools
                    ColumnLayout {
                        id: entry
                        required property var modelData
                        required property int index
                        readonly property bool firstOfGroup: index === 0 || Workshop.tools[index - 1].group !== modelData.group
                        readonly property bool on: Workshop.tool === modelData.id
                        Layout.fillWidth: true
                        spacing: 2
                        LcText {
                            visible: entry.firstOfGroup
                            text: entry.modelData.group
                            kind: "smallFaint"
                            font.weight: Font.DemiBold
                            Layout.leftMargin: Theme.sp2
                            Layout.topMargin: entry.index === 0 ? 0 : Theme.sp3
                            Layout.bottomMargin: 2
                        }
                        Rectangle {
                            objectName: "ws-tool-" + entry.modelData.id
                            Layout.fillWidth: true
                            implicitHeight: toolRow.implicitHeight + 14
                            radius: Theme.rMd
                            color: entry.on ? Theme.accentSoft : area.containsMouse ? Theme.surface3 : "transparent"
                            RowLayout {
                                id: toolRow
                                x: 10; y: 7
                                width: parent.width - 20
                                spacing: Theme.sp2
                                LcIcon { name: entry.modelData.icon; size: 16; width: 16; height: 16; color: entry.on ? Theme.accent : Theme.muted; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    LcText { text: entry.modelData.title; font.weight: entry.on ? Font.DemiBold : Font.Medium; Layout.fillWidth: true; elide: Text.ElideRight }
                                    LcText { text: entry.modelData.blurb; kind: "smallMuted"; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                            }
                            MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Workshop.tool = entry.modelData.id }
                        }
                    }
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
                    objectName: "ws-form-scroll"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: Theme.sp4
                    spacing: Theme.sp3
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        LcText { objectName: "ws-heading"; text: root.info.title || ""; kind: "h2"; Layout.fillWidth: true; elide: Text.ElideRight }
                        LcText { text: root.info.blurb || ""; kind: "muted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                    WsForm { Layout.fillWidth: true; visible: root.computes }

                    // Material test: the camera variant lives under Maschine.
                    LcNote {
                        visible: Workshop.tool === "materialtest"
                        Layout.fillWidth: true
                        text: "Hier entsteht das Raster als Teile im Projekt, gestartet wird wie jeder Auftrag unter Starten. Den Materialtest, der das Ergebnis mit der Kamera auswertet, gibt es unter Maschine, Kalibrieren."
                    }
                    LcButton {
                        objectName: "ws-to-matcal"
                        visible: Workshop.tool === "materialtest"
                        icon: "camera"; text: "Materialtest mit Kamera"
                        onClicked: { AppSettings.setValue("maschineTab", "kalibrieren"); Shell.navigate("maschine") }
                    }

                    // Photo engraving: the image tools are in Motiv.
                    ColumnLayout {
                        visible: Workshop.tool === "foto"
                        Layout.fillWidth: true
                        spacing: Theme.sp3
                        LcText {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: "Fotos bereitest du direkt im Motiv vor. Dort liegt das Bild auf der Platte, und die Vorschau zeigt sofort, was gelasert wird."
                        }
                        Repeater {
                            model: [
                                { icon: "image-plus", text: "Bild laden: Motiv, Bild (JPG, PNG, BMP). Es landet auf der Ebene Gravieren." },
                                { icon: "settings", text: "Rechts unter Eigenschaften: Verfahren (Graustufen, Punkte, feine Punkte, Schwelle), Helligkeit, Kontrast, Schärfen und Umkehren." },
                                { icon: "layers-3", text: "Zeilenabstand, Leistung und Tempo stehen an der Ebene Gravieren, die Tonkurve kommt aus dem gewählten Material." },
                                { icon: "flask-conical", text: "Vorher ein Materialtest-Raster auf demselben Material: dann stimmen Leistung und Tempo." }
                            ]
                            RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: Theme.sp2
                                LcIcon { name: parent.modelData.icon; size: 16; width: 16; height: 16; color: Theme.accent; Layout.alignment: Qt.AlignTop }
                                LcText { text: parent.modelData.text; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            }
                        }
                        LcButton {
                            objectName: "ws-foto-open"
                            variant: "primary"
                            icon: "image-plus"; text: "Foto im Motiv laden"
                            onClicked: { Shell.navigate("motiv"); Editor.askImport(true) }
                        }
                    }

                    // Result: notes and warnings.
                    LcNote {
                        objectName: "ws-error"
                        visible: root.computes && !!root.res.error
                        Layout.fillWidth: true
                        tone: "bad"
                        text: root.res.error || ""
                    }
                    Repeater {
                        model: root.computes && !root.res.error ? (root.res.warnings || []) : []
                        LcNote { required property var modelData; Layout.fillWidth: true; tone: "warn"; text: modelData }
                    }
                    Repeater {
                        model: root.computes && !root.res.error ? (root.res.notes || []) : []
                        LcText { required property var modelData; Layout.fillWidth: true; kind: "smallMuted"; wrapMode: Text.WordWrap; text: modelData }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line; visible: root.computes }
                RowLayout {
                    visible: root.computes
                    Layout.fillWidth: true
                    Layout.margins: Theme.sp3
                    spacing: Theme.sp2
                    LcButton {
                        objectName: "ws-reset"
                        icon: "undo-2"; variant: "ghost"
                        tip: "Werte zurücksetzen"
                        onClicked: Workshop.resetParams()
                    }
                    Item { Layout.fillWidth: true }
                    LcButton {
                        objectName: "ws-to-motiv"
                        icon: "pencil"; variant: "ghost"
                        tip: "Zum Motiv: dort liegen die übernommenen Teile"
                        onClicked: Shell.navigate("motiv")
                    }
                    LcButton {
                        objectName: "ws-apply"
                        variant: "primary"
                        icon: "plus"; text: "Ins Projekt"
                        lock: root.res.ok ? "" : (root.res.error || "Nichts zum Übernehmen")
                        tip: "Legt die Teile auf die aktive Platte, bei Bedarf auf neue Platten. Rückgängig mit Strg+Z im Motiv."
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
                objectName: "ws-stage"
                anchors.fill: parent
                interactive: true
                canvasColor: "transparent"
                sheetColor: Theme.sheet
                gridColor: Theme.grid
                gridMajorColor: Theme.gridMajor
                edgeColor: Theme.line2
                parkColor: Theme.park
                selectionColor: Theme.accent
                visible: root.computes
                Component.onCompleted: Workshop.attachPreview(stage)
                onWidthChanged: Workshop.fitPreview()
                onHeightChanged: Workshop.fitPreview()
            }
            RowLayout {
                visible: root.computes && root.res.ok
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: Theme.sp3
                spacing: Theme.sp2
                LcChip { objectName: "ws-size"; text: root.res.size || ""; icon: "ruler" }
                LcChip { text: (root.res.parts || 0) + (root.res.parts === 1 ? " Teil" : " Teile") }
                LcSegmented {
                    objectName: "ws-preview-plate"
                    visible: (root.res.plates || 0) > 1
                    value: Workshop.previewPlate
                    options: { const o = []; for (let i = 0; i < (root.res.plates || 0); ++i) o.push({ value: i, label: "Platte " + (i + 1) }); return o }
                    onActivated: (v) => Workshop.previewPlate = v
                }
            }
            LcButton {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.sp3
                visible: root.computes
                icon: "maximize-2"; variant: "ghost"
                tip: "Vorschau einpassen"
                onClicked: Workshop.fitPreview()
            }
            LcText {
                visible: root.computes
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: Theme.sp3
                elide: Text.ElideRight
                kind: "smallFaint"
                text: "Vorschau auf der Arbeitsfläche, so wie die Teile ins Projekt kommen. Mausrad zoomt, Ziehen verschiebt."
            }
            Column {
                visible: !root.computes
                anchors.centerIn: parent
                width: Math.min(parent.width - 2 * Theme.sp5, 420)
                spacing: Theme.sp2
                LcIcon { anchors.horizontalCenter: parent.horizontalCenter; name: "image"; size: 30; width: 30; height: 30; color: Theme.muted }
                LcText { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; kind: "muted"; text: "Die Fotogravur hat hier keine eigene Vorschau: das Bild und seine Einstellungen siehst du im Motiv." }
            }
        }
    }
}
