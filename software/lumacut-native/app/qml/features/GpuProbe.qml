import QtQuick
import LumaCut

// Stack test: a million instanced segments on the GPU, redrawn every frame while scrubbing.
Rectangle {
    id: root
    objectName: "gpuProbe"
    color: Theme.canvas
    function benchmark(n) { view.loadBenchmark(n); return n }
    Segments {
        id: view
        objectName: "segments"
        anchors.fill: parent
        cutColor: Theme.text; lowColor: Theme.accent; travelColor: Theme.faint
        sheetColor: Theme.sheet; gridColor: Theme.grid; gridMajorColor: Theme.gridMajor; edgeColor: Theme.line2; parkColor: Theme.park
        property int tick: 0
    }
    // Animated scrub: forces a real GPU frame continuously, as playing a job would.
    Timer {
        objectName: "scrub"
        interval: 1; repeat: true; running: view.segmentCount > 0
        onTriggered: view.visibleCount = 1 + (view.visibleCount + Math.max(1, view.segmentCount / 400)) % view.segmentCount
    }
}
