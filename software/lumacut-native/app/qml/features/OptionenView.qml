import QtQuick
import QtQuick.Layouts
import LumaCut

Item {
    id: root
    objectName: "view-Optionen"
    LcScroll {
        anchors.fill: parent
        padding: Theme.sp5
        maxContentWidth: 780
        spacing: Theme.sp3
        LcText { text: "Optionen"; kind: "h1"; Layout.bottomMargin: Theme.sp2 }

        // ---- Verbindung
        LcCard {
            id: conn
            objectName: "o-connection"
            Layout.fillWidth: true
            property string typed: AppSettings.piUrl
            readonly property var parsed: AppSettings.parseAddress(typed)
            readonly property string url: parsed.url || ""
            property int checkState: 0   // 0 idle, 1 checking, 2 ok, 3 bad
            property string checkText: ""
            function test() {
                if (!url) return
                checkState = 1
                Pi.testAddress(url, function (ok, text) { checkText = text; checkState = ok ? 2 : 3 })
            }
            RowLayout {
                Layout.fillWidth: true
                LcText { text: "Verbindung zum Pi"; kind: "h3"; Layout.fillWidth: true }
                LcChip {
                    objectName: "o-online"
                    readonly property string name: Machine.status.config ? (Machine.status.config.machine_name || "") : ""
                    text: Machine.online ? "Verbunden" + (name ? ": " + name : "") : "Nicht erreichbar"
                    tone: Machine.online ? "ok" : "bad"
                }
            }
            LcField {
                Layout.fillWidth: true
                label: "Adresse"
                hint: conn.parsed.error ? conn.parsed.error : conn.url !== conn.typed.trim() ? "Wird zu " + conn.url : ""
                RowLayout {
                    spacing: Theme.sp2
                    LcInput {
                        id: addr
                        objectName: "o-address"
                        Layout.fillWidth: true
                        mono: true
                        text: AppSettings.piUrl
                        onEdited: (t) => { conn.typed = t; conn.checkState = 0 }
                        onAccepted: conn.test()
                    }
                    LcButton { objectName: "o-test"; text: conn.checkState === 1 ? "Prüft" : "Prüfen"; enabled: !!conn.url && conn.checkState !== 1; onClicked: conn.test() }
                    LcButton {
                        objectName: "o-save"; text: "Speichern"; variant: "primary"
                        enabled: !!conn.url && conn.url !== AppSettings.piUrl
                        onClicked: { AppSettings.piUrl = conn.url; addr.text = conn.url; conn.typed = conn.url; Toast.show("Adresse gespeichert.", "ok") }
                    }
                }
            }
            LcNote { objectName: "o-check"; visible: conn.checkState >= 2; Layout.fillWidth: true; tone: conn.checkState === 2 ? "ok" : "bad"; text: conn.checkText }
            LcText { visible: Pi.overridden; text: "Diese Sitzung nutzt die Adresse aus LUMACUT_PI_URL: " + Pi.shortUrl; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            LcButton {
                visible: AppSettings.piUrl !== "http://192.168.2.89:8080"
                size: "sm"; variant: "ghost"
                text: "Vorgabe eintragen (192.168.2.89:8080)"
                onClicked: { addr.text = "http://192.168.2.89:8080"; conn.typed = addr.text }
            }
        }

        // ---- Darstellung
        LcCard {
            objectName: "o-theme"
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    LcText { text: "Darstellung"; kind: "h3"; Layout.fillWidth: true }
                    LcText { text: "System folgt der Einstellung von Windows."; kind: "muted" }
                }
                LcSegmented {
                    objectName: "o-theme-seg"
                    value: AppSettings.theme
                    options: [{ value: "light", label: "Hell", icon: "sun" }, { value: "dark", label: "Dunkel", icon: "moon" }, { value: "system", label: "System", icon: "monitor" }]
                    onActivated: (v) => AppSettings.theme = v
                }
            }
        }

        // ---- Update
        LcCard {
            objectName: "o-update"
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    LcText { text: "App-Version"; kind: "h3"; Layout.fillWidth: true }
                    LcText { objectName: "o-version"; text: Updater.current; kind: "muted"; tnum: true }
                }
                LcButton {
                    objectName: "o-check-update"
                    icon: "refresh-cw"; text: "Nach Update suchen"
                    busy: Updater.checking
                    enabled: !Updater.installing
                    onClicked: Updater.check()
                }
            }
            LcNote { objectName: "o-update-error"; visible: Updater.error.length > 0; Layout.fillWidth: true; tone: "bad"; text: "Prüfung fehlgeschlagen: " + Updater.error }
            LcNote { objectName: "o-update-result"; visible: Updater.checked && !Updater.error && !Updater.available; Layout.fillWidth: true; tone: "ok"; text: "Die App ist aktuell." }
            ColumnLayout {
                visible: Updater.available
                Layout.fillWidth: true
                spacing: Theme.sp3
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp3
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        LcText {
                            objectName: "o-update-version"
                            textFormat: Text.PlainText
                            font.weight: Font.DemiBold
                            text: "Version " + Updater.version + " ist verfügbar" + (Updater.sizeBytes ? ", " + Fmt.de(Updater.sizeBytes / 1e6) + " MB" : "")
                        }
                        LcText { visible: Updater.notes.length > 0; text: Updater.notes; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                    }
                    LcButton {
                        objectName: "o-install"
                        variant: "primary"; icon: "download"; text: "Installieren"
                        busy: Updater.installing
                        onClicked: Confirm.ask({ title: "Update installieren?", body: "Version " + Updater.version + " wird geladen und geprüft, dann startet das Setup und die App schließt sich. Ungespeicherte Änderungen vorher sichern.", okLabel: "Installieren" },
                                               function (yes) { if (yes) Updater.install() })
                    }
                }
                LcNote { Layout.fillWidth: true; tone: "info"; text: "Das Setup ist nicht signiert. Windows zeigt deshalb eine SmartScreen-Warnung: „Weitere Informationen“, dann „Trotzdem ausführen“." }
            }
        }

        // ---- Tastenkürzel
        LcCard {
            objectName: "o-keys"
            Layout.fillWidth: true
            spacing: Theme.sp4
            LcText { text: "Tastenkürzel"; kind: "h3" }
            Repeater {
                model: [
                    { area: "Überall", rows: [[["Pause"], "NOT-AUS"], [["Strg", "1…6"], "Material, Motiv, Starten, Platine, Werkstatt, Maschine"], [["Alt", "S"], "Im Freigabe-Dialog: Starten (Enter löst nie aus)"], [["Esc"], "Dialog schließen"]] },
                    { area: "Maschine, Reiter Steuerung", rows: [[["←", "↑", "↓", "→"], "Kopf einen Schritt bewegen, von der Tür gesehen"], [["Bild auf", "Bild ab"], "Kopf einen Schritt hoch oder runter"]] },
                    { area: "Zahlenfelder", rows: [[["Enter"], "Wert übernehmen"], [["↑", "↓"], "Wert ändern, mit Umschalt zehnfach"]] }
                ]
                ColumnLayout {
                    id: keyArea
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 5
                    LcText { text: keyArea.modelData.area; kind: "section" }
                    Repeater {
                        model: keyArea.modelData.rows
                        RowLayout {
                            id: keyRow
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: Theme.sp2
                            Row {
                                Layout.preferredWidth: 170
                                spacing: 3
                                Repeater { model: keyRow.modelData[0]; LcKbd { required property string modelData; text: modelData } }
                            }
                            LcText { text: keyRow.modelData[1]; kind: "muted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                    }
                }
            }
            LcText { text: "Die Kürzel des Motiv-Editors stehen dort in den Tooltips."; kind: "smallFaint" }
        }

        // ---- Über
        LcCard {
            objectName: "o-about"
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.sp3
                Rectangle {
                    Layout.preferredWidth: 34; Layout.preferredHeight: 34
                    Layout.alignment: Qt.AlignTop
                    radius: 9; color: Theme.accent
                    LcIcon { anchors.centerIn: parent; name: "zap"; size: 18; width: 18; height: 18; color: Theme.accentInk }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    LcText { text: "LumaCut Studio"; kind: "h3" }
                    LcText { text: "Software für den selbstgebauten Diodenlaser LumaCut. Einstellungen, Grenzen, Kalibrierungen, Materialien und Projekte liegen auf dem Pi, Tablet und PC greifen auf denselben Stand zu."; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    LcText { text: "Der NOT-AUS in der App ersetzt nicht den Schalter an der Maschine."; kind: "muted"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    LcText { text: "Nutzt Qt 6 (LGPL v3), Clipper2 (Boost) und die Icons von Lucide (ISC)."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                }
            }
        }
    }
}
