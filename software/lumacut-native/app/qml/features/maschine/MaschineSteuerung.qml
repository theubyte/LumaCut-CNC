import QtQuick
import QtQuick.Layouts
import LumaCut

// Status, single jog steps, and the actions. Every lock says why; the go dialog sits in MachineActions.
LcScroll {
    id: page
    objectName: "m-steuerung"
    padding: Theme.sp4
    maxContentWidth: 1560
    readonly property bool wide: width >= 1244
    readonly property bool narrow: width < 964
    readonly property var head: Machine.headline
    readonly property string busy: MachineActions.busyOp

    GridLayout {
        Layout.fillWidth: true
        columns: page.wide ? 3 : 2
        columnSpacing: Theme.sp4
        rowSpacing: Theme.sp4

        // ---- Left: state and work area
        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: 400
            Layout.minimumWidth: 280
            Layout.alignment: Qt.AlignTop
            spacing: Theme.sp4
            LcCard {
                objectName: "m-hero"
                Layout.fillWidth: true
                padding: Theme.sp5
                spacing: Theme.sp4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.sp3
                    Rectangle {
                        readonly property color tone: page.head.tone === "ok" ? Theme.ok : page.head.tone === "warn" ? Theme.warn : page.head.tone === "bad" ? Theme.bad : Theme.accent
                        Layout.preferredWidth: 12; Layout.preferredHeight: 12
                        Layout.alignment: Qt.AlignTop; Layout.topMargin: 9; Layout.leftMargin: 4
                        radius: 6
                        color: tone
                        Rectangle { anchors.fill: parent; anchors.margins: -4; radius: 10; color: Qt.alpha(parent.tone, .16); z: -1 }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        LcText { objectName: "m-headline"; text: page.head.title; kind: "h1"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        LcText { visible: text.length > 0; text: page.head.text; kind: "muted"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                }
                LcButton {
                    objectName: "m-estop-reset"
                    visible: Machine.latched
                    Layout.fillWidth: true
                    variant: "primary"; size: "lg"
                    text: "Not-Aus quittieren"
                    busy: page.busy === "estop_reset"
                    onClicked: MachineActions.run("estop_reset")
                }
                LcButton {
                    objectName: "m-home-next"
                    visible: !Machine.latched && Machine.online && Machine.status.connected !== false && !Machine.homed
                    Layout.fillWidth: true
                    variant: "primary"; size: "lg"; icon: "home"
                    text: "Referenzieren"
                    lock: Machine.homeLock
                    busy: page.busy === "home"
                    enabled: !page.busy.length || page.busy === "home"
                    onClicked: MachineActions.home()
                }
                Rectangle {
                    objectName: "m-pos"
                    Layout.fillWidth: true
                    implicitHeight: posRow.implicitHeight + 2 * Theme.sp3
                    radius: Theme.rLg
                    color: Theme.surface2
                    RowLayout {
                        id: posRow
                        anchors.fill: parent; anchors.margins: Theme.sp3
                        spacing: Theme.sp2
                        LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; large: true; label: "X"; valueName: "m-x"; value: Machine.hasPosition ? Fmt.de(Machine.workX) : "–" }
                        LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; large: true; label: "Y"; valueName: "m-y"; value: Machine.hasPosition ? Fmt.de(Machine.workY) : "–" }
                        LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; large: true; label: "Z"; valueName: "m-z"; value: Machine.hasPosition ? Fmt.de(Machine.z) : "–" }
                    }
                }
                LcText { text: "Position von der Tür gesehen, Ursprung links hinten, in mm."; kind: "smallFaint"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: Theme.sp4
                    rowSpacing: Theme.sp3
                    LcStat { Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Referenz"; valueName: "m-homed"; value: Machine.homed ? "Ja" : "Nein"; tone: Machine.homed ? "" : "warn" }
                    LcStat {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Werkstück Z"; valueName: "m-surface"
                        value: Fmt.isNumber(Machine.status.workpiece_surface_z) ? Fmt.de(Machine.status.workpiece_surface_z, 2) + " mm" : "–"
                    }
                    LcStat {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Fokus Z"
                        value: Fmt.isNumber(Machine.status.laser_focus_z) ? Fmt.de(Machine.status.laser_focus_z, 2) + " mm" : "–"
                    }
                    LcStat {
                        Layout.fillWidth: true; Layout.preferredWidth: 1; mono: false; label: "Material"; valueName: "m-material"
                        value: Workspace.hasMaterial ? Workspace.materialName + ", " + Fmt.de(Workspace.materialThickness) + " mm" : "keins gewählt"
                        tone: Workspace.hasMaterial ? "" : "warn"
                    }
                }
            }
        }

        // ---- Middle: jog
        LcCard {
            id: jog
            objectName: "m-jog"
            Layout.preferredWidth: page.narrow ? 340 : 372
            Layout.alignment: Qt.AlignTop
            padding: page.narrow ? Theme.sp4 : Theme.sp5
            spacing: Theme.sp4
            readonly property int key: page.narrow ? 58 : 66
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                LcText { text: "Bewegen"; kind: "h3"; Layout.fillWidth: true }
                LcSegmented {
                    objectName: "jog-step"
                    value: MachineActions.jogStep
                    options: [{ value: 0.1, label: "0,1" }, { value: 1, label: "1" }, { value: 10, label: "10" }]
                    onActivated: (v) => MachineActions.jogStep = v
                }
                LcText { text: "mm"; kind: "faint" }
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.sp5
                Grid {
                    columns: 3
                    spacing: 6
                    Item { width: jog.key; height: jog.key }
                    JogKey { dir: "up"; icon: "arrow-up"; label: "Nach hinten (Pfeil hoch)" }
                    Item { width: jog.key; height: jog.key }
                    JogKey { dir: "left"; icon: "arrow-left"; label: "Nach links (Pfeil links)" }
                    Item { width: jog.key; height: jog.key; LcText { anchors.centerIn: parent; text: "X Y"; kind: "smallFaint"; font.weight: Font.DemiBold } }
                    JogKey { dir: "right"; icon: "arrow-right"; label: "Nach rechts (Pfeil rechts)" }
                    Item { width: jog.key; height: jog.key }
                    JogKey { dir: "down"; icon: "arrow-down"; label: "Nach vorne (Pfeil runter)" }
                    Item { width: jog.key; height: jog.key }
                }
                Column {
                    spacing: 6
                    JogKey { dir: "zup"; icon: "arrow-up"; label: "Kopf hoch (Bild auf)"; zAxis: true }
                    Item { width: jog.key; height: jog.key; LcText { anchors.centerIn: parent; text: "Z"; kind: "smallFaint"; font.weight: Font.DemiBold } }
                    JogKey { dir: "zdown"; icon: "arrow-down"; label: "Kopf runter (Bild ab)"; zAxis: true }
                }
            }
            MLockLine { text: Machine.moveLock || Machine.zLock }
            Flow {
                visible: !Machine.moveLock && !Machine.zLock
                Layout.fillWidth: true
                spacing: 3
                LcKbd { text: "←" } LcKbd { text: "↑" } LcKbd { text: "↓" } LcKbd { text: "→" }
                LcText { text: " bewegen, "; kind: "smallFaint" }
                LcKbd { text: "Bild auf" } LcKbd { text: "Bild ab" }
                LcText { text: " für Z. Jeder Druck ein Schritt."; kind: "smallFaint" }
            }
            component JogKey: Rectangle {
                id: jk
                property string dir
                property string icon
                property string label
                property bool zAxis: false
                readonly property string lock: zAxis ? Machine.zLock : Machine.moveLock
                readonly property bool down: mouse.pressed || MachineActions.jogActive === dir
                objectName: "jog-" + dir
                width: jog.key; height: jog.key
                radius: Theme.rLg
                color: lock ? Theme.surface : down ? Theme.accentSoft : mouse.containsMouse ? Theme.surface3 : Theme.surface
                border.width: 1
                border.color: down && !lock ? Theme.accent : Theme.line2
                opacity: lock ? .4 : 1
                activeFocusOnTab: !lock
                LcIcon { anchors.centerIn: parent; name: jk.icon; size: 22; width: 22; height: 22; color: jk.down && !jk.lock ? Theme.accent : Theme.text }
                Rectangle { anchors.fill: parent; anchors.margins: -2; radius: parent.radius + 2; color: "transparent"; border.width: 2; border.color: Theme.accent; visible: parent.activeFocus }
                Keys.onSpacePressed: (e) => { if (!e.isAutoRepeat) MachineActions.jog(dir) }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: jk.lock ? Qt.ForbiddenCursor : Qt.PointingHandCursor
                    onClicked: MachineActions.jog(jk.dir)
                }
                LcTip { shown: mouse.containsMouse; text: jk.lock || jk.label }
            }
        }

        // ---- Right, or across below: actions
        LcCard {
            objectName: "m-actions"
            Layout.fillWidth: true
            Layout.preferredWidth: 460
            Layout.columnSpan: page.wide ? 1 : 2
            Layout.alignment: Qt.AlignTop
            padding: Theme.sp4
            spacing: Theme.sp1
            LcText { text: "Aktionen"; kind: "h3"; Layout.bottomMargin: Theme.sp1 }
            MLockLine { text: Machine.moveLock; Layout.bottomMargin: Theme.sp1 }
            GridLayout {
                Layout.fillWidth: true
                columns: !page.wide && !page.narrow ? 2 : 1
                columnSpacing: Theme.sp5
                rowSpacing: 0
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                    spacing: 0
                    MActionRow {
                        objectName: "row-home"; icon: "home"; title: "Referenzfahrt"; sub: "X und Y an die Endschalter, dann Z."
                        LcButton {
                            objectName: "m-home"; text: "Referenzieren"
                            lock: Machine.homeLock; busy: page.busy === "home"
                            enabled: !page.busy.length || page.busy === "home"
                            onClicked: MachineActions.home()
                        }
                    }
                    MActionRow {
                        objectName: "row-probe"; icon: "scan-line"; title: "Abtasten"
                        sub: Machine.probeLock && !Machine.moveLock ? Machine.probeLock : "Misst die Oberfläche unter dem Laserpunkt."
                        subColor: Machine.probeLock && !Machine.moveLock ? Theme.warn : Theme.muted
                        LcButton {
                            objectName: "m-probe"; text: "Abtasten"
                            lock: Machine.probeLock; busy: page.busy === "probe"; enabled: !page.busy.length
                            onClicked: MachineActions.run("probe")
                        }
                    }
                    MActionRow {
                        objectName: "row-park"; icon: "parking-square"; title: "Parken"; sub: "Kopf in die Park-Ecke."
                        LcButton {
                            objectName: "m-park"; text: "Parken"
                            lock: Machine.moveLock; busy: page.busy === "park"; enabled: !page.busy.length
                            onClicked: MachineActions.run("park")
                        }
                    }
                    MActionRow {
                        objectName: "row-moveto"; icon: "navigation"; title: "Zu Position fahren"
                        below: RowLayout {
                            width: Math.min(parent.width, 240)
                            spacing: 6
                            LcNumber { id: toX; objectName: "moveto-x"; Layout.fillWidth: true; value: 100; min: 0; max: Machine.bedWidth; digits: 1; unit: "X"; onEdited: (v) => value = v }
                            LcNumber { id: toY; objectName: "moveto-y"; Layout.fillWidth: true; value: 100; min: 0; max: Machine.bedHeight; digits: 1; unit: "Y"; onEdited: (v) => value = v }
                            LcButton {
                                objectName: "moveto-here"; icon: "crosshair"; variant: "ghost"; size: "sm"
                                tip: "Aktuelle Kopfposition eintragen"
                                enabled: Machine.hasPosition
                                onClicked: { toX.value = +Machine.workX.toFixed(1); toY.value = +Machine.workY.toFixed(1) }
                            }
                        }
                        LcButton {
                            objectName: "m-moveto"; text: "Fahren"
                            lock: Machine.moveLock; busy: page.busy === "moveto"; enabled: !page.busy.length
                            onClicked: MachineActions.moveTo(toX.value, toY.value)
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.topMargin: 3; Layout.bottomMargin: 3; color: Theme.line; visible: page.wide || page.narrow }
                }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                    spacing: 0
                    MActionRow {
                        id: lightRow
                        objectName: "row-light"; icon: "lightbulb"; title: "Licht"
                        sub: Machine.status.light_dimmable === false ? "Diese Firmware kann nicht dimmen." : ""
                        property real level: 60
                        property double editedAt: 0
                        readonly property var piLevel: Machine.status.light_brightness
                        onPiLevelChanged: if (Date.now() - editedAt > 1500 && Fmt.isNumber(piLevel)) level = Math.round(piLevel)
                        below: LcSlider {
                            visible: Machine.status.light_dimmable !== false
                            width: parent.width
                            objectName: "light-level"
                            enabled: !Machine.freeLock
                            value: lightRow.level
                            min: 1; max: 100; unit: "%"
                            onMoved: (v) => { lightRow.level = v; lightRow.editedAt = Date.now(); lightSend.restart() }
                        }
                        Timer { id: lightSend; interval: 300; onTriggered: MachineActions.run("light", { on: "1", brightness: Math.round(lightRow.level) }, { quiet: true }) }
                        LcSwitch {
                            objectName: "m-light"; on: Machine.lights; lock: Machine.freeLock
                            anchors.verticalCenter: parent.verticalCenter
                            onToggled: (v) => MachineActions.run("light", { on: v ? "1" : "0" }, { quiet: true })
                        }
                    }
                    MActionRow {
                        objectName: "row-exhaust"; icon: "fan"; title: "Abluft"
                        sub: Machine.status.config && Machine.status.config.exhaust_auto ? "Läuft beim Auftrag von selbst, " + (Machine.status.config.exhaust_after_s || 0) + " s Nachlauf." : "Nur von Hand."
                        LcSwitch {
                            objectName: "m-exhaust"; on: Machine.exhaust; lock: Machine.freeLock
                            anchors.verticalCenter: parent.verticalCenter
                            onToggled: (v) => MachineActions.run("exhaust", { on: v ? "1" : "0" }, { quiet: true })
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.topMargin: 3; Layout.bottomMargin: 3; color: Theme.line; visible: page.wide || page.narrow }
                    MActionRow {
                        objectName: "row-origin"; icon: "map-pin"; title: "Ursprung"
                        readonly property var user: Machine.status.origin ? Machine.status.origin.user : null
                        sub: user ? "Gesetzt auf X " + Fmt.de(Machine.fromMachine(user[0], user[1]).x) + ", Y " + Fmt.de(user[1]) + "." : "Keiner gesetzt. Aufträge laufen wie entworfen."
                        LcButton {
                            objectName: "m-origin-set"; text: "Hier setzen"; lock: Machine.moveLock
                            tip: "Aktuelle Kopfposition als Ursprung speichern, fährt nicht"
                            onClicked: MachineActions.run("origin_set")
                        }
                        LcButton {
                            objectName: "m-origin-clear"; text: "Löschen"; variant: "ghost"
                            visible: !!(Machine.status.origin && Machine.status.origin.user)
                            onClicked: Calibration.clearOrigin()
                        }
                    }
                    MActionRow {
                        readonly property var bed: Machine.status.bed_map
                        objectName: "row-bedmap"; icon: "grid-3x3"; title: "Bettkarte"
                        sub: bed ? bed.cols + " × " + bed.rows + " Punkte, Spanne " + Fmt.de(bed.range, 2) + " mm, " + Fmt.when(bed.measured_at) : "Noch nicht gemessen. Das Bett muss dafür leer sein."
                        LcButton {
                            objectName: "m-bedmap"; text: "Messen"
                            lock: Machine.probeLock; busy: page.busy === "bedmap"; enabled: !page.busy.length
                            onClicked: MachineActions.run("bedmap")
                        }
                        LcButton {
                            objectName: "m-bedmap-clear"; text: "Löschen"; variant: "ghost"
                            visible: !!Machine.status.bed_map
                            onClicked: Calibration.clearBedMap()
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.topMargin: 3; Layout.bottomMargin: 3; color: Theme.line }
                    MActionRow {
                        id: bandRow
                        objectName: "row-band"; icon: "ban"; title: "Oberer Streifen"
                        readonly property bool on: Machine.blockedBandY > 0
                        sub: on ? "Y 0 bis " + Fmt.trim(Machine.blockedBandY, 0) + " mm über die ganze Breite gesperrt. Fahren bleibt erlaubt." : "Nur die Park-Ecke ist gesperrt. Für einen aufgeklebten Streifen über die ganze Breite einschalten."
                        below: RowLayout {
                            width: parent.width
                            spacing: Theme.sp3
                            MBedMini { Layout.preferredWidth: 100; Layout.preferredHeight: 96 }
                            LcField {
                                visible: bandRow.on
                                Layout.preferredWidth: 90
                                Layout.alignment: Qt.AlignTop
                                label: "Sperren bis Y"
                                LcNumber {
                                    objectName: "band-y"; value: Machine.blockedBandY; min: 35; max: 120; digits: 0; unit: "mm"
                                    enabled: !Machine.freeLock
                                    onEdited: (v) => MachineActions.run("work_band", { y: v })
                                }
                            }
                            Item { Layout.fillWidth: true; visible: bandRow.on }
                        }
                        LcSwitch {
                            objectName: "m-band"; on: bandRow.on; lock: Machine.freeLock
                            anchors.verticalCenter: parent.verticalCenter
                            onToggled: (v) => MachineActions.run("work_band", { y: v ? 35 : "" })
                        }
                    }
                }
            }
        }
    }

    // Single steps only: no repeat on a held key, nothing while typing or under a dialog (Shell checks both).
    Connections {
        target: Shell
        enabled: page.visible
        function onJogKey(key) {
            const d = key === Qt.Key_Left ? "left" : key === Qt.Key_Right ? "right" : key === Qt.Key_Up ? "up" : key === Qt.Key_Down ? "down" : key === Qt.Key_PageUp ? "zup" : "zdown"
            MachineActions.jog(d)
        }
    }
}
