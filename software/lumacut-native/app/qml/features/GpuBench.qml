import QtQuick
import LumaCut

// Test bench for the GPU items in the real window. Only ever created by the automation (command "gpuBench"),
// on top of everything else; not part of the app's navigation.
Rectangle {
    id: root
    objectName: "gpuBench"
    anchors.fill: parent
    color: Theme.canvas
    property string page: "segments"

    function show(p) { page = p; return page }
    function theme(dark) { Theme.dark = dark; return Theme.dark }
    function loadSegments(n) { segments.loadBenchmark(n); return n }
    function setZoomAt(a) { segments.zoomAt(Qt.point(a.x, a.y), a.f); return segments.effectiveZoom }
    function fitAll(_) { segments.fit(); stage.fit(); return true }
    function playTo(n) { segments.visibleCount = n; return n }
    function travel(v) { segments.showTravel = v; return v }
    function burnMap(v) { segments.burnMap = v; return v }
    function pending(v) { segments.pendingOpacity = v; return v }
    function continuous(v) {   // only what is on the page: a hidden item would keep drawing and spoil the measurement
        segments.continuous = v && page === "segments"; stage.continuous = v && page === "stage"; compute.continuous = v && page === "compute"
        return v
    }
    function powerColor(v) { segments.lowColor = v ? Theme.accent : Theme.text; return v }
    function loadStage(a) { stage.loadBenchmark(a.paths, a.segs); return a.paths }
    function stageMove(a) { return stage.benchmarkMove(a.step, a.dx, a.dy) }
    function stageReshape(i) { stage.benchmarkReshape(i); return i }
    function stageImage(_) { stage.benchmarkImage(); return true }
    function stageSelect(a) { stage.benchmarkSelect(a.n, Qt.rect(a.x, a.y, a.w, a.h)); return true }
    function stageZoom(a) { stage.zoomAt(Qt.point(a.x, a.y), a.f); return stage.effectiveZoom }
    function stageEvenOdd(_) { stage.benchmarkEvenOdd(); return true }
    function stageHide(id) { stage.benchmarkHide(id); return id }
    function stageToItem(a) { const p = stage.mmToItem(Qt.point(a.x, a.y)); return { x: p.x, y: p.y } }
    function segToMm(a) { const p = segments.itemToMm(Qt.point(a.x, a.y)); return { x: p.x, y: p.y } }
    function segToItem(a) { const p = segments.mmToItem(Qt.point(a.x, a.y)); return { x: p.x, y: p.y } }
    function computeLoad(mp) { compute.loadTestImage(mp); return mp }
    function computeSet(a) { compute.mode = a.mode; compute.contrast = a.contrast; compute.brightness = a.brightness; return true }
    function computeBench(mp) { compute.startBenchmark(mp); return mp }

    Segments {
        id: segments
        objectName: "benchSegments"
        anchors.fill: parent
        visible: root.page === "segments"
        interactive: true
        sheetColor: Theme.sheet; gridColor: Theme.grid; gridMajorColor: Theme.gridMajor; edgeColor: Theme.line2; parkColor: Theme.park
        canvasColor: Theme.canvas
        cutColor: Theme.text; lowColor: Theme.text; travelColor: Theme.faint
    }
    Stage {
        id: stage
        objectName: "benchStage"
        anchors.fill: parent
        visible: root.page === "stage"
        interactive: true
        sheetColor: Theme.sheet; gridColor: Theme.grid; gridMajorColor: Theme.gridMajor; edgeColor: Theme.line2; parkColor: Theme.park
        canvasColor: Theme.canvas
        selectionColor: Theme.accent
    }
    ComputeImage {
        id: compute
        objectName: "benchCompute"
        anchors.fill: parent
        visible: root.page === "compute"
    }
}
