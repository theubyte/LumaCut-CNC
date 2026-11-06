pragma Singleton
import QtQuick

// Design tokens: same palette family as the Android app (ui/Theme.kt). All colours and sizes come from here.
QtObject {
    // "system", "light" or "dark"; Main.qml binds it to the settings store.
    property string pref: "system"
    property bool dark: pref === "dark" || (pref === "system" && Qt.styleHints.colorScheme === Qt.Dark)
    readonly property color bg: dark ? "#0e1016" : "#f2f3f9"
    readonly property color surface: dark ? "#171a23" : "#ffffff"
    readonly property color surface2: dark ? "#1d2130" : "#f6f7fc"
    readonly property color surface3: dark ? "#272c3d" : "#eceef7"
    readonly property color line: dark ? "#262b39" : "#e4e7f1"
    readonly property color line2: dark ? "#383e54" : "#cfd4e5"
    readonly property color text: dark ? "#eef0f8" : "#151827"
    readonly property color muted: dark ? "#a6acc2" : "#555b73"
    readonly property color faint: dark ? "#7f859d" : "#7a8097"
    readonly property color accent: dark ? "#8f9bff" : "#4a57e3"
    readonly property color accentHover: dark ? "#a5afff" : "#3d49cf"
    readonly property color accentInk: dark ? "#0d113d" : "#ffffff"
    readonly property color accentSoft: dark ? Qt.rgba(143/255, 155/255, 1, .16) : Qt.rgba(74/255, 87/255, 227/255, .10)
    readonly property color ok: dark ? "#4fd8a4" : "#12855a"
    readonly property color warn: dark ? "#f2b45c" : "#ad6500"
    readonly property color bad: dark ? "#ff6b70" : "#cf3340"
    readonly property color info: dark ? "#6cb6ff" : "#2c68d6"
    readonly property color okSoft: Qt.alpha(ok, dark ? .14 : .11)
    readonly property color warnSoft: Qt.alpha(warn, dark ? .14 : .11)
    readonly property color badSoft: Qt.alpha(bad, dark ? .14 : .10)
    readonly property color infoSoft: Qt.alpha(info, dark ? .14 : .10)
    readonly property color estop: dark ? "#d92c35" : "#d7262f"
    readonly property color estopHover: dark ? "#ec3a43" : "#bb1c25"
    readonly property color canvas: dark ? "#0a0c11" : "#e9ebf5"
    readonly property color sheet: dark ? "#131722" : "#ffffff"
    readonly property color grid: dark ? Qt.rgba(166/255, 172/255, 194/255, .08) : Qt.rgba(64/255, 74/255, 128/255, .08)
    readonly property color gridMajor: dark ? Qt.rgba(166/255, 172/255, 194/255, .19) : Qt.rgba(64/255, 74/255, 128/255, .18)
    readonly property color park: Qt.alpha(bad, dark ? .13 : .10)
    readonly property color scrim: dark ? Qt.rgba(3/255, 4/255, 8/255, .58) : Qt.rgba(18/255, 20/255, 34/255, .34)

    readonly property color shadowSoft: dark ? Qt.rgba(0, 0, 0, .45) : Qt.rgba(21/255, 24/255, 39/255, .12)
    readonly property color shadowStrong: dark ? Qt.rgba(0, 0, 0, .6) : Qt.rgba(21/255, 24/255, 39/255, .24)

    readonly property string font: "Segoe UI Variable Text"
    readonly property string fontDisplay: "Segoe UI Variable Display"
    readonly property string mono: "Cascadia Mono"
    readonly property int fsXs: 11
    readonly property int fsSm: 12
    readonly property int fsMd: 13
    readonly property int fsLg: 15
    readonly property int fsXl: 18
    readonly property int fs2xl: 24
    readonly property int fs3xl: 32
    readonly property int rSm: 5
    readonly property int rMd: 7
    readonly property int rLg: 10
    readonly property int rXl: 14
    readonly property int sp1: 4
    readonly property int sp2: 8
    readonly property int sp3: 12
    readonly property int sp4: 16
    readonly property int sp5: 24
    readonly property int sp6: 32
    readonly property int hControlSm: 24
    readonly property int hControl: 30
    readonly property int hControlLg: 38
    readonly property int topbar: 46
    readonly property int rail: 76
    readonly property int statusbar: 26
    readonly property int panel: 288
    readonly property int mvBar: 42
    readonly property int mvTools: 44
    readonly property int mvSide: 304
    readonly property int mvPlates: 34
    readonly property int ruler: 24
    readonly property int panelWide: 376
    readonly property int dockBody: 232
    readonly property int tFast: 90
    readonly property int tMed: 160
}
