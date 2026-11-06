import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import LumaCut

// The work area to scale with park corner, the job on the GPU, zoom, pan and a playback along the job.
ColumnLayout {
    id: root
    spacing: 0

    Item {
        id: stage
        objectName: "start-stage"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        Rectangle { anchors.fill: parent; color: Theme.canvas }

        Segments {
            id: view
            objectName: "start-preview"
            anchors.fill: parent
            anchors.leftMargin: Theme.sp6
            anchors.topMargin: Theme.sp5
            anchors.rightMargin: Theme.sp4
            anchors.bottomMargin: Theme.sp4
            interactive: true
            bedWidth: Machine.bedWidth
            bedHeight: Machine.bedHeight
            parkWidth: Machine.parkX
            parkHeight: Machine.parkY
            sheetColor: Theme.sheet
            gridColor: Theme.grid
            gridMajorColor: Theme.gridMajor
            edgeColor: Theme.line2
            parkColor: Theme.park
            cutColor: Theme.text
            lowColor: Theme.text
            travelColor: Qt.alpha(Theme.faint, 0.5)
            pendingOpacity: 0.3
            visibleCount: Start.visibleCount
            showTravel: Start.showTravel
            Component.onCompleted: JobBuilder.attachPreview(view)
            TapHandler { onDoubleTapped: view.fit() }
            Connections { target: Start; function onSourceSwitched() { view.fit() } }
        }

        // Where the bed lies in this item: every overlay reckons from here.
        readonly property real k: view.effectiveZoom
        readonly property point origin: { view.effectiveZoom; view.pan; return view.mapToItem(stage, view.mmToItem(Qt.point(0, 0))) }
        readonly property real fitK: Math.min(view.width / Math.max(1, Machine.bedWidth), view.height / Math.max(1, Machine.bedHeight)) * 0.96
        function originX() { return origin.x }      // for the test driver
        function benchmark(n) { view.continuous = n > 0; view.loadBenchmark(n); return n }   // tests/ui/test_smoke.py, bench_stack.py: synthetic segments, redrawn every frame
        function sx(mm) { return origin.x + mm * k }
        function sy(mm) { return origin.y + mm * k }

        // Scale along the top and left edge, in work mm. A fixed pool of labels: nothing is created while zooming.
        readonly property int tick: { const t = [10, 20, 50, 100].find((v) => v * k >= 44); return t === undefined ? 200 : t }
        readonly property real leftMm: Math.max(0, -origin.x / k)
        readonly property real rightMm: Math.min(Machine.bedWidth, (width - origin.x) / k)
        readonly property real topMm: Math.max(0, -origin.y / k)
        readonly property real bottomMm: Math.min(Machine.bedHeight, (height - origin.y) / k)
        readonly property real rulerY: Math.max(origin.y, Theme.sp5) - Theme.fsXs - Theme.sp1 - 3
        readonly property real rulerX: Math.max(origin.x, Theme.sp6) - Theme.sp2
        Repeater {
            model: Math.max(0, Math.floor(stage.rightMm / stage.tick) - Math.ceil(stage.leftMm / stage.tick) + 1)
            LcText {
                required property int index
                readonly property int mm: (Math.ceil(stage.leftMm / stage.tick) + index) * stage.tick
                text: String(mm)
                kind: "smallFaint"; tnum: true; font.pixelSize: Theme.fsXs
                x: stage.sx(mm) - width / 2
                y: stage.rulerY
            }
        }
        Repeater {
            model: Math.max(0, Math.floor(stage.bottomMm / stage.tick) - Math.ceil(Math.max(stage.topMm, 1) / stage.tick) + 1)
            LcText {
                required property int index
                readonly property int mm: (Math.ceil(Math.max(stage.topMm, 1) / stage.tick) + index) * stage.tick
                text: String(mm)
                kind: "smallFaint"; tnum: true; font.pixelSize: Theme.fsXs
                x: stage.rulerX - width
                y: stage.sy(mm) - height / 2
            }
        }
        LcText {
            objectName: "start-park-label"
            readonly property real w: Machine.parkX * stage.k
            readonly property real h: Machine.parkY * stage.k
            visible: w > implicitWidth + Theme.sp2 && h > implicitHeight
            text: Start.parkName
            kind: "small"; color: Theme.bad; font.pixelSize: Theme.fsXs; font.weight: Font.Medium
            x: stage.sx(Machine.bedWidth) - w / 2 - width / 2
            y: stage.sy(Machine.parkY / 2) - height / 2
        }

        // Dashed outline of what burns: this is what "Rahmen" drives along.
        Shape {
            id: outline
            objectName: "start-bounds"
            visible: Start.hasBounds
            readonly property real x0: Math.round(stage.sx(Start.boundsX0)) - 2.5
            readonly property real y0: Math.round(stage.sy(Start.boundsY0)) - 2.5
            readonly property real x1: Math.round(stage.sx(Start.boundsX1)) + 2.5
            readonly property real y1: Math.round(stage.sy(Start.boundsY1)) + 2.5
            anchors.fill: parent
            ShapePath {
                strokeColor: Theme.faint
                strokeWidth: 1
                fillColor: "transparent"
                strokeStyle: ShapePath.DashLine
                dashPattern: [4, 5]
                startX: outline.x0; startY: outline.y0
                PathLine { x: outline.x1; y: outline.y0 }
                PathLine { x: outline.x1; y: outline.y1 }
                PathLine { x: outline.x0; y: outline.y1 }
                PathLine { x: outline.x0; y: outline.y0 }
            }
        }

        // The head while the machine moves, or the playback's position.
        Item {
            objectName: "start-head"
            visible: Start.headVisible
            x: stage.sx(Start.head.x)
            y: stage.sy(Start.head.y)
            Rectangle { x: -6; y: -6; width: 12; height: 12; radius: 6; color: "transparent"; border.width: 1.5; border.color: Theme.accent }
            Rectangle { x: -11; y: -0.75; width: 8; height: 1.5; color: Theme.accent }
            Rectangle { x: 3; y: -0.75; width: 8; height: 1.5; color: Theme.accent }
            Rectangle { x: -0.75; y: -11; width: 1.5; height: 8; color: Theme.accent }
            Rectangle { x: -0.75; y: 3; width: 1.5; height: 8; color: Theme.accent }
        }

        // A new job is on its way while the old one is still shown.
        LcChip {
            objectName: "start-rebuilding"
            visible: Start.overlay === "" && (JobBuilder.building || view.loading)
            text: "Wird berechnet …"
            tone: "accent"
            anchors.horizontalCenter: view.horizontalCenter
            anchors.top: view.top
            anchors.topMargin: Theme.sp2
        }

        Rectangle {
            objectName: "start-zoom"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Theme.sp3
            width: zoomRow.implicitWidth + Theme.sp1 * 2
            height: Theme.hControl + Theme.sp1
            radius: Theme.rMd
            color: Theme.surface
            border.width: 1
            border.color: Theme.line
            Row {
                id: zoomRow
                anchors.centerIn: parent
                spacing: 2
                LcButton { objectName: "start-zoom-out"; icon: "minus"; size: "sm"; variant: "ghost"; tip: "Verkleinern (Mausrad)"; onClicked: view.zoomAt(Qt.point(view.width / 2, view.height / 2), 1 / 1.4) }
                LcText {
                    objectName: "start-zoom-value"
                    width: Theme.sp6 + Theme.sp4
                    height: Theme.hControlSm
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: Math.round(100 * stage.k / Math.max(0.0001, stage.fitK)) + " %"
                    kind: "smallMuted"; tnum: true
                }
                LcButton { objectName: "start-zoom-in"; icon: "plus"; size: "sm"; variant: "ghost"; tip: "Vergrößern (Mausrad)"; onClicked: view.zoomAt(Qt.point(view.width / 2, view.height / 2), 1.4) }
                LcButton { objectName: "start-zoom-fit"; icon: "maximize"; size: "sm"; variant: "ghost"; tip: "Ganze Fläche (Doppelklick)"; onClicked: view.fit() }
            }
        }

        LcCard {
            objectName: "start-empty"
            visible: Start.overlay !== ""
            anchors.centerIn: view
            width: Math.min(view.width - Theme.sp5 * 2, Theme.panelWide)
            padding: Theme.sp5
            spacing: Theme.sp2
            LcText { objectName: "start-empty-title"; text: Start.emptyTitle; kind: "h3"; Layout.alignment: Qt.AlignHCenter; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            LcText { visible: text.length > 0; text: Start.emptyText; kind: "muted"; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap }
            LcButton {
                objectName: "start-to-motif"
                visible: Start.overlay === "empty"
                text: "Zum Motiv"; variant: "primary"
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Theme.sp2
                onClicked: Shell.navigate("motiv")
            }
        }
    }

    FrameAnimation {
        running: Start.playing
        onTriggered: Start.advance(frameTime)
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Theme.hControlLg + Theme.sp1
        color: Theme.surface
        Rectangle { width: parent.width; height: 1; color: Theme.line }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.sp3
            anchors.rightMargin: Theme.sp3
            spacing: Theme.sp3
            Row {
                spacing: 2
                enabled: Start.segmentCount > 0 && !Start.live
                LcButton { objectName: "start-to-begin"; icon: "skip-back"; size: "sm"; variant: "ghost"; tip: "Zum Anfang"; onClicked: Start.toBeginning() }
                LcButton { objectName: "start-step-back"; icon: "chevron-left"; size: "sm"; variant: "ghost"; tip: "Eine Bahn zurück"; onClicked: Start.step(-1) }
                LcButton { objectName: "start-play"; icon: Start.playing ? "pause" : "play"; size: "sm"; variant: "ghost"; tip: Start.playing ? "Anhalten" : "Abspielen"; onClicked: Start.togglePlay() }
                LcButton { objectName: "start-step-forward"; icon: "chevron-right"; size: "sm"; variant: "ghost"; tip: "Eine Bahn vor"; onClicked: Start.step(1) }
            }
            LcSlider {
                objectName: "start-slider"
                Layout.fillWidth: true
                enabled: Start.segmentCount > 0 && !Start.live
                showNumber: false
                min: 0
                max: Math.max(1, Start.segmentCount)
                step: 1
                value: Start.sliderValue
                onMoved: (v) => Start.scrub(Math.round(v))
            }
            LcText { objectName: "start-readout"; text: Start.readout; kind: "smallMuted"; tnum: true }
            LcCheck {
                objectName: "start-travel"
                text: "Leerfahrten"
                checked: Start.showTravel
                onToggled: (on) => { Start.showTravel = on }
            }
        }
    }
}
