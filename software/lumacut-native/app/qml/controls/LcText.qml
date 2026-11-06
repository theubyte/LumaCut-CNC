import QtQuick
import LumaCut

// Text with the app's type scale. kind: body, muted, faint, small, smallMuted, smallFaint, h1, h2, h3, section, mono, monoLg
Text {
    property string kind: "body"
    property bool tnum: false
    readonly property bool _mono: kind === "mono" || kind === "monoLg"
    readonly property bool _display: kind === "h1" || kind === "h2"
    color: kind === "muted" || kind === "smallMuted" || kind === "section" ? Theme.muted
         : kind === "faint" || kind === "smallFaint" ? Theme.faint : Theme.text
    renderType: Text.NativeRendering
    font.family: _mono ? Theme.mono : _display ? Theme.fontDisplay : Theme.font
    font.pixelSize: kind === "h1" ? Theme.fs2xl : kind === "h2" ? Theme.fsXl : kind === "h3" ? Theme.fsLg : kind === "monoLg" ? Theme.fsXl
                  : kind === "small" || kind === "smallMuted" || kind === "smallFaint" || kind === "section" ? Theme.fsSm : Theme.fsMd
    font.weight: kind === "h1" || kind === "h2" || kind === "h3" || kind === "section" || kind === "monoLg" ? Font.DemiBold : Font.Normal
    font.features: tnum || _mono ? { "tnum": 1 } : ({})
    lineHeight: 1.0
}
