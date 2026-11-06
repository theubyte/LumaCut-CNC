import QtQuick
import QtQuick.Layouts
import LumaCut

// Live picture as a GPU texture. Stops with the tab, with a hidden window, and during jobs: the job may need the camera itself.
LcScroll {
    id: page
    objectName: "m-kamera"
    maxContentWidth: 1800
    property bool paused: false
    readonly property int frames: live.frames
    readonly property bool available: Machine.cameraAvailable
    readonly property bool job: Machine.jobActive
    Component.onCompleted: Calibration.loadCamera()
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.sp4
        LcCard {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            padding: Theme.sp2
            spacing: Theme.sp2
            Rectangle {
                id: preview
                objectName: "cam-preview"
                Layout.fillWidth: true
                Layout.preferredHeight: width * 9 / 16
                color: Theme.canvas
                PiImage {
                    id: live
                    objectName: "cam-image"
                    anchors.fill: parent
                    path: "/api/camera/snapshot?w=1280&h=720"
                    gapMs: 250
                    running: Machine.online && page.available && !page.paused && !page.job
                }
                Column {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 2 * Theme.sp6, 420)
                    spacing: Theme.sp2
                    visible: !page.available || (!live.hasImage && !live.error)
                    LcIcon { anchors.horizontalCenter: parent.horizontalCenter; name: "camera"; size: 28; width: 28; height: 28; color: Theme.muted }
                    LcText {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        kind: "muted"
                        text: !page.available ? (Machine.online ? "Keine Kamera am Pi. Kopfkamera anschließen, dann erscheint hier das Bild." : "Pi nicht erreichbar. Adresse unter Optionen prüfen.")
                            : page.job ? "Während eines Auftrags ruht die Vorschau, damit die Kamera frei bleibt."
                            : page.paused ? "Vorschau angehalten." : "Erstes Bild wird geholt."
                    }
                }
                LcNote {
                    visible: live.error.length > 0 && page.available
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                    anchors.margins: Theme.sp3
                    tone: "bad"
                    text: live.error + " Nächster Versuch in 3 Sekunden."
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.sp3
                LcButton {
                    objectName: "cam-pause"
                    text: page.paused ? "Weiter" : "Anhalten"
                    icon: page.paused ? "play" : "pause"
                    enabled: page.available
                    onClicked: page.paused = !page.paused
                }
                LcText {
                    objectName: "cam-state"
                    Layout.fillWidth: true
                    kind: "muted"
                    elide: Text.ElideRight
                    text: page.job ? "Ruht während des Auftrags." : page.paused ? "Angehalten." : live.frames > 0 ? "Live, " + Fmt.de(live.frameMs / 1000) + " s je Bild" : ""
                }
                LcText { visible: page.available && page.width > 1100; text: "Das Licht geht für die Vorschau von selbst an und danach wieder aus."; kind: "smallFaint" }
            }
        }
        ColumnLayout {
            Layout.preferredWidth: 340
            Layout.maximumWidth: 340
            Layout.alignment: Qt.AlignTop
            spacing: Theme.sp4
            LcCard {
                objectName: "cam-settings"
                Layout.fillWidth: true
                LcText { text: "Bild"; kind: "h3" }
                LcNote { visible: Calibration.cameraError.length > 0; text: Calibration.cameraError; tone: "bad"; Layout.fillWidth: true }
                LcText { visible: !Calibration.camera.ranges && !Calibration.cameraError; text: "Wird geladen."; kind: "muted" }
                FixedSlider { label: "Belichtung"; autoName: "cam-exp-auto"; key: "exposure"; fallback: 500; range: rangeOf("exposure", [1, 10000]) }
                FixedSlider { label: "Weißabgleich"; autoName: "cam-wb-auto"; key: "white_balance"; fallback: 4500; unit: "K"; range: rangeOf("white_balance", [2000, 10000]) }
                LcText { visible: !page.available; text: "Die Werte gelten, sobald eine Kamera angeschlossen ist."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                LcText { text: "Feste Werte machen Scans gleichmäßig. Sie gelten für alle Geräte."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            LcCard {
                id: calCard
                objectName: "cam-calibration"
                Layout.fillWidth: true
                readonly property var cal: Calibration.calibration
                readonly property var and: cal.android || ({})
                RowLayout {
                    Layout.fillWidth: true
                    LcText { text: "Kalibrierung"; kind: "h3"; Layout.fillWidth: true }
                    LcChip { text: Calibration.cameraOk ? "kalibriert" : "fehlt"; tone: Calibration.cameraOk ? "ok" : "warn" }
                }
                LcText { visible: !Calibration.cameraOk; text: "Noch keine Messung. Scan und Materialtest brauchen sie. Die Kalibrierung mit dem Punktraster läuft bisher in der Tablet-App."; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                GridLayout {
                    visible: Calibration.cameraOk
                    Layout.fillWidth: true
                    columns: 2; columnSpacing: Theme.sp4; rowSpacing: Theme.sp3
                    LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Bildgröße"; value: (calCard.and.photoWidth || calCard.cal.image_width || "–") + " × " + (calCard.and.photoHeight || calCard.cal.image_height || "–") }
                    LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Genauigkeit"; value: calCard.and.lens && Fmt.isNumber(calCard.and.lens.rmsMm) ? Fmt.de(calCard.and.lens.rmsMm, 2) + " mm" : "–" }
                    LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Stand"; value: Fmt.when(calCard.cal.updated_at) }
                    LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Von"; value: calCard.cal.updated_by || "–" }
                }
            }
            LcCard {
                objectName: "cam-scan"
                Layout.fillWidth: true
                LcText { text: "Arbeitsplatz-Scan"; kind: "h3" }
                Rectangle {
                    // stays visible while empty: an invisible image item would never load
                    Layout.fillWidth: true
                    Layout.preferredHeight: scan.hasImage ? width * 360 / 370 : 0
                    radius: Theme.rMd
                    color: Theme.canvas
                    PiImage {
                        id: scan
                        objectName: "cam-scan-image"
                        anchors.fill: parent
                        path: "/api/workspace/scan?rev=" + Workspace.scanRevision
                        running: Machine.online
                    }
                }
                LcText { visible: scan.notFound; text: "Auf dem Pi liegt noch kein Scan."; kind: "muted" }
                LcText { visible: scan.error.length > 0; text: "Der Scan ließ sich nicht laden."; kind: "muted" }
                LcText { text: "Neu scannen geht bisher nur in der Tablet-App. Das Ergebnis erscheint hier und im Editor."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
        }
    }

    function rangeOf(key, fallback) { const r = Calibration.camera.ranges; return r && r[key] ? r[key] : fallback }

    component FixedSlider: ColumnLayout {
        id: fs
        property string label
        property string autoName
        property string key
        property real fallback
        property string unit
        property var range: [0, 100]
        readonly property var stored: Calibration.camera[key]
        readonly property bool fixed: Fmt.isNumber(stored)
        property real local: fallback
        onStoredChanged: if (fixed) local = stored
        visible: !!Calibration.camera.ranges
        Layout.fillWidth: true
        spacing: 3
        RowLayout {
            Layout.fillWidth: true
            LcText { text: fs.label; kind: "smallMuted"; Layout.fillWidth: true }
            LcCheck {
                objectName: fs.autoName
                text: "Automatisch"
                checked: !fs.fixed
                onToggled: (on) => {
                    const p = {}
                    p[fs.key] = on ? null : Math.min(fs.range[1], Math.max(fs.range[0], fs.local))
                    Calibration.saveCamera(p)
                }
            }
        }
        LcSlider {
            visible: fs.fixed
            Layout.fillWidth: true
            value: fs.local
            min: fs.range[0]; max: fs.range[1]; unit: fs.unit
            onMoved: (v) => fs.local = v
            onCommitted: { const p = {}; p[fs.key] = fs.local; Calibration.saveCamera(p) }
        }
        LcText { visible: !fs.fixed; text: "Die Kamera regelt selbst."; kind: "faint"; Layout.preferredHeight: Theme.hControl; verticalAlignment: Text.AlignVCenter }
    }
}
