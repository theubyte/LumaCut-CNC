import QtQuick
import QtQuick.Layouts
import LumaCut

// One layer: what it is, power and speed at once, the rest folds out.
Rectangle {
    id: root
    required property string layerId
    property bool dragging: false
    signal gripPosition(real sceneY)
    signal gripReleased()
    readonly property var r: Editor.layerRow(layerId, Editor.layersRev)
    readonly property string nameKey: r.name || ""
    readonly property int maxFeed: { const m = Machine.status.config && Machine.status.config.motion ? Machine.status.config.motion.speed : 0; return m > 0 ? m : 30000 }
    property bool open: false
    objectName: "layer-" + nameKey
    implicitHeight: body.implicitHeight + Theme.sp2 + 6
    height: implicitHeight
    radius: Theme.rMd
    color: r.focused || rowHover.hovered ? Theme.surface2 : "transparent"
    border.width: 1
    border.color: r.focused ? Theme.line : "transparent"
    opacity: dragging ? .55 : 1
    readonly property bool off: !r.visible || !r.output
    HoverHandler { id: rowHover }
    TapHandler { onTapped: Document.activeLayer = root.layerId }

    ColumnLayout {
        id: body
        x: Theme.sp1; y: 6
        width: parent.width - Theme.sp1 - Theme.sp2
        spacing: Theme.sp1
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            Item {
                objectName: "layer-grip-" + root.nameKey
                Layout.preferredWidth: 16
                Layout.preferredHeight: Theme.hControlSm
                LcIcon { anchors.centerIn: parent; name: "grip-vertical"; size: 14; width: 14; height: 14; color: gripArea.containsMouse ? Theme.text : Theme.faint }
                MouseArea {
                    id: gripArea
                    anchors.fill: parent
                    hoverEnabled: true
                    preventStealing: true
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    onPositionChanged: (m) => { if (pressed) root.gripPosition(mapToItem(null, m.x, m.y).y) }
                    onReleased: root.gripReleased()
                }
                LcTip { shown: gripArea.containsMouse && !gripArea.pressed; text: "Ziehen ändert die Reihenfolge beim Lasern" }
            }
            Rectangle {
                id: swatch
                objectName: "layer-color-" + root.nameKey
                Layout.preferredWidth: 12
                Layout.preferredHeight: 12
                Layout.leftMargin: 2; Layout.rightMargin: 6
                radius: 3
                color: root.r.color || Theme.faint
                opacity: root.off ? .35 : 1
                border.width: 1
                border.color: Theme.line2
                MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: colorPop.openAt(swatch) }
                LcTip { shown: false; text: "Farbe ändern" }
            }
            LcText {
                visible: root.r.standard === true
                Layout.fillWidth: true
                text: root.r.label || ""
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                color: root.off ? Theme.faint : Theme.text
            }
            TextInput {
                id: nameInput
                objectName: "layer-name-" + root.nameKey
                visible: root.r.standard !== true
                Layout.fillWidth: true
                text: root.r.name || ""
                color: root.off ? Theme.faint : Theme.text
                font.family: Theme.font
                font.pixelSize: Theme.fsMd
                font.weight: Font.DemiBold
                selectByMouse: true
                renderType: TextInput.NativeRendering
                onEditingFinished: { if (text.trim().length && text !== root.r.name) Editor.setLayerValue(root.layerId, "name", text.trim()) }
            }
            LcText {
                text: root.r.count !== undefined ? root.r.count : ""
                kind: "smallFaint"
                font.pixelSize: Theme.fsXs
                tnum: true
                Layout.rightMargin: 2
            }
            LcButton {
                objectName: "layer-visible-" + root.nameKey
                variant: "ghost"; size: "sm"
                icon: root.r.visible ? "eye" : "eye-off"
                tip: root.r.visible ? "Ausblenden, wird dann auch nicht gelasert" : "Einblenden"
                onClicked: Editor.setLayerValue(root.layerId, "visible", !root.r.visible)
            }
            LcButton {
                objectName: "layer-output-" + root.nameKey
                variant: "ghost"; size: "sm"
                icon: root.r.output ? "zap" : "zap-off"
                textColor: root.r.output ? Theme.accent : Theme.muted
                tip: root.r.output ? "Wird gelasert. Klick: nicht lasern" : "Wird nicht gelasert. Klick: lasern"
                onClicked: Editor.setLayerValue(root.layerId, "output", !root.r.output)
            }
            LcButton {
                objectName: "layer-more-" + root.nameKey
                variant: "ghost"; size: "sm"
                icon: root.open ? "chevron-down" : "chevron-right"
                tip: "Weitere Werte"
                onClicked: root.open = !root.open
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            spacing: 6
            LcNumber {
                objectName: "layer-power-" + root.nameKey
                Layout.preferredWidth: 78
                implicitHeight: 26
                value: root.r.power !== undefined ? root.r.power : 0
                unit: "%"; step: 1; min: 0; max: 100; digits: 1
                tip: "Leistung"
                onEdited: (v) => Editor.setLayerValue(root.layerId, "powerPct", v)
            }
            LcNumber {
                objectName: "layer-speed-" + root.nameKey
                Layout.fillWidth: true
                implicitHeight: 26
                value: root.r.speed !== undefined ? root.r.speed : 0
                unit: "mm/min"; step: 100; min: 1; max: root.maxFeed; digits: 0
                tip: "Tempo, höchstens " + root.maxFeed + " mm/min"
                onEdited: (v) => Editor.setLayerValue(root.layerId, "speed", v)
            }
        }
        LcText {
            objectName: "layer-lowpower-" + root.nameKey
            visible: root.r.lowPower === true
            Layout.fillWidth: true
            Layout.leftMargin: 16
            text: "Unter " + root.r.minPower + " % zündet der Laser nicht sicher."
            kind: "small"
            color: Theme.warn
            font.pixelSize: Theme.fsXs
            wrapMode: Text.WordWrap
        }
        LcText {
            objectName: "layer-incoming-" + root.nameKey
            visible: (root.r.incoming || 0) > 0 && !root.r.focused && root.r.standard !== true
            Layout.leftMargin: 16
            text: "Auswahl hierher (" + (root.r.incoming || 0) + ")"
            kind: "small"
            color: Theme.accent
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { Document.activeLayer = root.layerId; Editor.moveSelectionToLayer(root.layerId) } }
        }
        Rectangle { visible: root.open; Layout.fillWidth: true; Layout.leftMargin: 16; Layout.topMargin: Theme.sp1; Layout.preferredHeight: 1; color: Theme.line }
        ColumnLayout {
            visible: root.open
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.topMargin: Theme.sp1
            spacing: Theme.sp2
            LcField {
                Layout.fillWidth: true
                label: "Art"
                LcSegmented {
                    objectName: "layer-process-" + root.nameKey
                    implicitWidth: 120
                    value: root.r.process || ""
                    options: [{ value: "Gravieren", label: "Gravieren" }, { value: "Linie", label: "Markieren" }, { value: "Schneiden", label: "Schneiden" }]
                    onActivated: (v) => Editor.setLayerProcess(root.layerId, v)
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.sp2
                rowSpacing: Theme.sp2
                LcField {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Durchgänge"
                    LcNumber { objectName: "layer-passes-" + root.nameKey; implicitHeight: 26; value: root.r.passes || 1; unit: "×"; min: 1; max: 30; digits: 0; onEdited: (v) => Editor.setLayerValue(root.layerId, "passes", Math.round(v)) }
                }
                LcField {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Fokus-Absenkung"
                    LcNumber {
                        objectName: "layer-zstep-" + root.nameKey
                        implicitHeight: 26
                        value: root.r.zStep || 0
                        unit: "mm"; step: 0.1; min: 0; max: 2; digits: 2
                        enabled: (root.r.passes || 1) > 1
                        tip: "Fokus-Absenkung je Durchgang"
                        onEdited: (v) => Editor.setLayerValue(root.layerId, "zStepMm", v)
                    }
                }
                LcField {
                    visible: root.r.fill === true
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Zeilenabstand"
                    LcNumber { objectName: "layer-interval-" + root.nameKey; implicitHeight: 26; value: root.r.interval || 0.1; unit: "mm"; step: 0.01; min: 0.03; max: 2; digits: 3; onEdited: (v) => Editor.setLayerValue(root.layerId, "intervalMm", v) }
                }
                LcField {
                    visible: root.r.fill === true
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Überlauf"
                    LcNumber { objectName: "layer-overscan-" + root.nameKey; implicitHeight: 26; value: root.r.overscan !== undefined ? root.r.overscan : 0; unit: "mm"; step: 0.5; min: 0; max: 30; digits: 1; onEdited: (v) => Editor.setLayerValue(root.layerId, "overscanMm", v) }
                }
            }
            LcText {
                visible: (root.r.passes || 1) > 1 && (root.r.zStep || 0) > 0
                Layout.fillWidth: true
                text: "Fokus sinkt insgesamt um " + Fmt.de(root.r.focusDrop || 0, 2) + " mm, höchstens 3 mm, danach zurück."
                kind: "smallFaint"
                wrapMode: Text.WordWrap
            }
            LcText {
                visible: (root.r.materialName || "").length > 0
                Layout.fillWidth: true
                text: "Werte aus " + root.r.materialName + ((root.r.thickness || 0) > 0 ? ", " + Fmt.trim(root.r.thickness, 2) + " mm" : "") + "."
                kind: "smallFaint"
                wrapMode: Text.WordWrap
            }
            LcButton {
                objectName: "layer-delete-" + root.nameKey
                variant: "ghost"; size: "sm"
                icon: "trash-2"
                text: "Ebene löschen"
                onClicked: {
                    const n = root.r.count || 0
                    if (n === 0) { Editor.deleteLayer(root.layerId); return }
                    Confirm.ask({ title: "Ebene " + root.r.label + " löschen?", body: (n === 1 ? "1 Teil wird" : n + " Teile werden") + " mitgelöscht, auch auf anderen Platten. Rückgängig holt alles zurück.", okLabel: "Löschen", danger: true },
                                (yes) => { if (yes) Editor.deleteLayer(root.layerId) })
                }
            }
        }
    }

    MvPopover {
        id: colorPop
        objectName: "layer-color-pop-" + root.nameKey
        popWidth: 172
        Grid {
            columns: 6
            spacing: 6
            Repeater {
                model: ["#4fd8b4", "#6cb6ff", "#ff6b70", "#ffb45c", "#b98cff", "#ff8ad8", "#9be15d", "#5ce1e6", "#f2d14a", "#8f9bff", "#a6acc2", "#3a3f55"]
                Rectangle {
                    required property string modelData
                    required property int index
                    objectName: "layer-color-" + root.nameKey + "-" + index
                    width: 20; height: 20; radius: 5
                    color: modelData
                    border.width: root.r.color === modelData ? 2 : 1
                    border.color: root.r.color === modelData ? Theme.text : Theme.line2
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { Editor.setLayerValue(root.layerId, "color", modelData); colorPop.open = false } }
                }
            }
        }
    }
}
