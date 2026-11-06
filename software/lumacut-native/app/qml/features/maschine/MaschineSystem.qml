import QtQuick
import QtQuick.Layouts
import LumaCut

// What runs where. Flashing happens only on site at the machine, not from this app.
LcScroll {
    id: page
    objectName: "m-system"
    maxContentWidth: 1080
    readonly property var st: Machine.status
    readonly property var cfg: st.config || ({})
    readonly property var fw: st.firmware_release || ({})
    readonly property var upd: st.firmware_update || ({})
    readonly property var panel: st.panel || ({})
    readonly property var sys: Calibration.system
    function backupTo(path) { Calibration.saveBackup(path, null); return path }
    Timer { interval: 15000; running: page.visible && Machine.online; repeat: true; triggeredOnStart: true; onTriggered: Calibration.loadSystem() }
    LcNote { visible: !Machine.online; tone: "bad"; Layout.fillWidth: true; text: "Pi nicht erreichbar. Die Werte unten sind der letzte bekannte Stand. Adresse unter Optionen prüfen." }
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: Theme.sp4
        rowSpacing: Theme.sp4
        LcCard {
            objectName: "sys-firmware"
            Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
            RowLayout {
                Layout.fillWidth: true
                LcText { text: "Firmware"; kind: "h3"; Layout.fillWidth: true }
                LcChip { text: Machine.connected ? "verbunden" : "nicht verbunden"; tone: Machine.connected ? "ok" : "bad" }
            }
            LcText { text: Calibration.firmwareName; kind: "mono"; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
            GridLayout {
                Layout.fillWidth: true
                columns: 2; columnSpacing: Theme.sp4; rowSpacing: Theme.sp3
                LcStat {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Update"
                    value: page.fw.update_available ? "Verfügbar: " + (page.fw.release_build || page.fw.number || "") : page.fw.error ? "Prüfung fehlgeschlagen" : page.fw.checked_at ? "Aktuell" : "Noch nicht geprüft"
                    tone: page.fw.update_available ? "warn" : ""
                }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Zuletzt geprüft"; value: Fmt.when(page.fw.checked_at) }
                LcStat {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Update-Status"
                    value: page.upd.state && page.upd.state !== "idle" ? page.upd.state + (page.upd.progress !== undefined ? ", " + page.upd.progress + " %" : "") : "Kein Update läuft"
                }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Serielle Fehler"; value: page.st.serial_errors !== undefined ? page.st.serial_errors : "–"; tone: page.st.serial_errors ? "warn" : "" }
            }
            LcText { visible: !!page.fw.error; text: page.fw.error || ""; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { visible: !!page.upd.message; text: page.upd.message || ""; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcText { text: "Geflasht wird nur vor Ort an der Maschine, nicht aus dieser App."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        LcCard {
            objectName: "sys-pi"
            Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
            LcText { text: "Pi"; kind: "h3" }
            LcNote { visible: Calibration.systemError.length > 0; text: Calibration.systemError; tone: "bad"; Layout.fillWidth: true }
            GridLayout {
                Layout.fillWidth: true
                columns: 2; columnSpacing: Theme.sp4; rowSpacing: Theme.sp3
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Softwarestand"; value: page.sys.software_commit ? page.sys.software_commit.slice(0, 8) : "–" }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Stand vom"; value: Fmt.when(page.sys.software_date) }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Freier Speicher"; value: Calibration.gbText(page.sys.disk_free_bytes) + " von " + Calibration.gbText(page.sys.disk_total_bytes) }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Temperatur"; value: Fmt.isNumber(page.sys.cpu_temp_c) ? Fmt.de(page.sys.cpu_temp_c) + " °C" : "–"; tone: page.sys.cpu_temp_c > 75 ? "warn" : "" }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Dienst läuft seit"; value: Calibration.uptimeText(page.sys.service_uptime_s) }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Gespeicherte Aufträge"; value: Fmt.isNumber(page.sys.jobs_bytes) ? Fmt.de(page.sys.jobs_bytes / 1e6) + " MB" : "–" }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
            LcButton {
                objectName: "sys-backup"
                text: "Sicherung herunterladen"; icon: "download"
                enabled: Machine.online
                onClicked: {
                    const path = Calibration.askSavePath("lumacut-sicherung-" + new Date().toISOString().slice(0, 10) + ".json")
                    if (path) page.backupTo(path)
                }
            }
            LcText { text: "Einstellungen, Materialien, Arbeitsstand, Kalibrierungen. Ohne Aufträge, Projekte und Scan."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        LcCard {
            objectName: "sys-mechanik"
            Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
            RowLayout {
                Layout.fillWidth: true
                LcText { text: "Mechanik-Freigabe"; kind: "h3"; Layout.fillWidth: true }
                LcChip { text: page.cfg.validated ? "freigegeben" : "nicht freigegeben"; tone: page.cfg.validated ? "ok" : "warn" }
            }
            LcText { text: page.cfg.validated ? "Referenzfahrt, Fahren und Aufträge sind erlaubt." : "Ohne Freigabe lehnt der Pi Referenzfahrt, Fahren und Aufträge ab. Sie wird vor Ort an der Maschine erteilt."; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            GridLayout {
                Layout.fillWidth: true
                columns: 2; columnSpacing: Theme.sp4
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Fahrweg X × Y × Z"; value: page.cfg.travels ? page.cfg.travels.x + " × " + page.cfg.travels.y + " × " + page.cfg.travels.z + " mm" : "–" }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Gerätename"; value: page.cfg.machine_name || "–" }
            }
        }
        LcCard {
            objectName: "sys-panel"
            Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
            RowLayout {
                Layout.fillWidth: true
                LcText { text: "Bedienpanel"; kind: "h3"; Layout.fillWidth: true }
                LcChip { text: page.panel.connected ? "verbunden" : "nicht verbunden"; tone: page.panel.connected ? "ok" : "" }
            }
            GridLayout {
                visible: !!page.panel.connected
                Layout.fillWidth: true
                columns: 2; columnSpacing: Theme.sp4
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Version"; value: page.panel.version || "–" }
                LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Auf dem Pi"; value: page.panel.available || "–" }
            }
            LcText { visible: !page.panel.connected; text: "Kein Panel am USB des Pi."; kind: "muted" }
            LcText { visible: !!page.panel.message; text: page.panel.message || ""; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        LcCard {
            objectName: "sys-recent"
            Layout.fillWidth: true
            Layout.columnSpan: 2
            LcText { text: "Letzte Meldungen der Steuerung"; kind: "h3" }
            Rectangle {
                visible: Calibration.recentLines.length > 0
                Layout.fillWidth: true
                implicitHeight: log.implicitHeight + 2 * Theme.sp3
                radius: Theme.rMd
                color: Theme.surface2
                LcText { id: log; x: Theme.sp3; y: Theme.sp3; width: parent.width - 2 * Theme.sp3; text: Calibration.recentLines.join("\n"); kind: "mono"; color: Theme.muted; font.pixelSize: Theme.fsSm; wrapMode: Text.WrapAnywhere }
            }
            LcText { visible: !Calibration.recentLines.length; text: "Noch keine Meldungen."; kind: "muted" }
            LcNote { visible: !!page.st.fault; tone: "warn"; text: page.st.fault || ""; Layout.fillWidth: true }
        }
    }
}
