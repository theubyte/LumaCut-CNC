import QtQuick
import QtQuick.Layouts
import LumaCut

// Layers that carry something, top to bottom in the order they are lasered.
ColumnLayout {
    id: root
    objectName: "layers-panel"
    spacing: Theme.sp2
    readonly property int selCount: Editor.sel.count || 0
    property string dragId: ""
    property string dropBefore: ""
    property real dropY: -1

    function gripMoved(id, sceneY) {
        dragId = id
        let before = ""
        let y = -1
        for (let i = 0; i < rows.count; i++) {
            const it = rows.itemAt(i)
            const p = it.mapToItem(null, 0, 0)
            if (sceneY < p.y + it.height / 2) { before = it.layerId; y = it.y; break }
        }
        if (y < 0 && rows.count) { const l = rows.itemAt(rows.count - 1); y = l.y + l.height }
        dropBefore = before
        dropY = y
    }
    function gripDone() {
        if (dragId.length) {
            const order = Editor.layerIds, from = order.indexOf(dragId), to = dropBefore.length ? order.indexOf(dropBefore) : order.length
            if (to !== from && to !== from + 1) Editor.moveLayer(dragId, dropBefore)
        }
        dragId = ""; dropY = -1
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp2
        Layout.topMargin: Theme.sp3
        LcText { text: "Ebenen"; font.weight: Font.DemiBold; Layout.fillWidth: true }
        LcButton { objectName: "layer-add"; variant: "ghost"; size: "sm"; icon: "plus"; tip: "Eigene Ebene hinzufügen"; onClicked: Editor.addLayer() }
    }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        spacing: Theme.sp1
        LcText {
            objectName: "process-label"
            text: root.selCount ? "Auswahl (" + root.selCount + ") soll:" : "Neue Formen sollen:"
            kind: "smallMuted"
        }
        LcSegmented {
            objectName: "process"
            Layout.fillWidth: true
            implicitWidth: 120   // stretched: its own implicit width would follow the segments and never settle
            value: Editor.processValue
            options: [
                { value: "Gravieren", label: "Gravieren", tip: "Flächen zeilenweise füllen" },
                { value: "Linie", label: "Markieren", tip: "Der Linie folgen, nicht durchtrennen" },
                { value: "Schneiden", label: "Schneiden", tip: "Der Linie folgen, durchtrennen" }
            ]
            onActivated: (v) => Editor.pickProcess(v)
        }
    }
    LcText {
        visible: Editor.layerIds.length === 0
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        text: "Ebenen erscheinen von selbst, sobald etwas darauf liegt."
        kind: "smallFaint"
        wrapMode: Text.WordWrap
    }
    Item {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp2; Layout.rightMargin: Theme.sp2
        implicitHeight: col.implicitHeight
        visible: Editor.layerIds.length > 0
        Column {
            id: col
            width: parent.width
            spacing: 2
            Repeater {
                id: rows
                model: Editor.layerIds
                MvLayerRow {
                    required property string modelData
                    width: col.width
                    layerId: modelData
                    dragging: root.dragId === modelData
                    onGripPosition: (y) => root.gripMoved(modelData, y)
                    onGripReleased: root.gripDone()
                }
            }
        }
        Rectangle {
            visible: root.dropY >= 0
            y: root.dropY - 1
            x: Theme.sp1
            width: parent.width - 2 * Theme.sp1
            height: 2
            radius: 1
            color: Theme.accent
        }
    }
    LcNote {
        objectName: "cut-warning"
        visible: Editor.cutNotLast
        tone: "warn"
        Layout.fillWidth: true
        Layout.leftMargin: Theme.sp3; Layout.rightMargin: Theme.sp3
        text: "Schneiden läuft nicht zuletzt: ausgeschnittene Teile können verrutschen, bevor der Rest gelasert ist."
    }
    Item { Layout.preferredHeight: Theme.sp1 }
}
