import QtQuick
import LumaCut

// Small busy ring. Rotates on the render thread, costs nothing while hidden.
LcIcon {
    id: spin
    name: "loader-circle"
    size: 14
    width: size; height: size
    color: Theme.muted
    RotationAnimator on rotation { from: 0; to: 360; duration: 800; loops: Animation.Infinite; running: spin.visible }
}
