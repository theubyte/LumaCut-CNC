import QtQuick
import QtQuick.Layouts
import LumaCut

// One simple field of a workshop form: num, seg, text, check. Controls are named ws-<key>.
Item {
    id: root
    required property var field
    readonly property var current: Workshop.params[field.key]
    implicitHeight: loader.implicitHeight
    implicitWidth: loader.implicitWidth
    Loader {
        id: loader
        width: root.width
        sourceComponent: root.field.type === "num" ? numC : root.field.type === "seg" ? segC : root.field.type === "text" ? textC : checkC
    }
    Component {
        id: numC
        LcField {
            label: root.field.label
            hint: root.field.hint || ""
            LcNumber {
                objectName: "ws-" + root.field.key
                value: root.current === undefined ? 0 : root.current
                min: root.field.min; max: root.field.max; step: root.field.step; digits: root.field.digits
                unit: root.field.unit || ""
                onEdited: (v) => Workshop.setParam(root.field.key, v)
            }
        }
    }
    Component {
        id: segC
        LcField {
            label: root.field.label
            hint: root.field.hint || ""
            LcSegmented {
                objectName: "ws-" + root.field.key
                options: root.field.options
                value: root.current
                onActivated: (v) => Workshop.setParam(root.field.key, v)
            }
        }
    }
    Component {
        id: textC
        LcField {
            label: root.field.label
            hint: root.field.hint || ""
            LcInput {
                objectName: "ws-" + root.field.key
                placeholder: root.field.placeholder || ""
                Component.onCompleted: text = root.current === undefined ? "" : root.current
                onEdited: (t) => Workshop.setParam(root.field.key, t)
            }
        }
    }
    Component {
        id: checkC
        LcCheck {
            objectName: "ws-" + root.field.key
            text: root.field.label
            checked: !!root.current
            onToggled: (on) => Workshop.setParam(root.field.key, on)
        }
    }
}
