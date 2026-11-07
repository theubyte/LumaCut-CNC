import QtQuick
import LumaCut

// Test handles for the driver (tests/ui/test_scan.py), always reachable while the motif is open. Draws nothing.
Item {
    objectName: "scan-panel"
    width: 0; height: 0
    // Test handles for the driver.
    function showBackground(on) { Editor.bgOn = on; return Editor.bgOn }
    function reloadCalibration(_) { Scanner.loadCalibration(); return true }
    function scanArea(a) { Scanner.scanArea(a[0], a[1], a[2], a[3]); return true }
    function state(_) { return { calibrated: Scanner.calibrated, note: Scanner.calibrationNote, running: Scanner.running, step: Scanner.step, steps: Scanner.steps,
                                 result: Scanner.lastResult, rev: Scanner.backgroundRevision, stamp: Scanner.backgroundStamp, frames: Scanner.liveFrames,
                                 liveError: Scanner.liveError, lock: Scanner.lock([]), bgLoaded: Editor.bgLoaded, bgOn: Editor.bgOn, liveOn: Scanner.liveOn, overlayArea: Scanner.overlayArea, overlay: Scanner.liveOverlay } }
}
