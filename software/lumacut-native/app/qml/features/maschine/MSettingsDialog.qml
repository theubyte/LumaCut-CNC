import QtQuick
import QtQuick.Layouts
import LumaCut

// Entered values go to /api/settings; the Pi then forgets the measured surface, so the operator is told first.
// fields: [{ key, label, value, min, max, digits? }]
LcDialog {
    id: dlg
    property var fields: []
    property string note
    property var values: ({})
    onOpenChanged: if (open) { const v = {}; for (const f of fields) v[f.key] = f.value; values = v }
    onRejected: open = false
    dialogWidth: 480
    GridLayout {
        Layout.fillWidth: true
        columns: 2; columnSpacing: Theme.sp3; rowSpacing: Theme.sp3
        Repeater {
            model: dlg.open ? dlg.fields : []
            LcField {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                label: modelData.label
                LcNumber {
                    objectName: "set-" + parent.parent.modelData.key
                    value: parent.parent.modelData.value
                    min: parent.parent.modelData.min; max: parent.parent.modelData.max
                    step: 0.1; digits: parent.parent.modelData.digits || 2; unit: "mm"
                    onEdited: (v) => { value = v; dlg.values[parent.parent.modelData.key] = v }
                }
            }
        }
    }
    LcNote { Layout.fillWidth: true; tone: "warn"; text: dlg.note }
    footer: [
        LcButton { objectName: "settings-cancel"; text: "Abbrechen"; onClicked: dlg.open = false },
        LcButton {
            objectName: "settings-save"; text: "Speichern"; variant: "primary"
            onClicked: Calibration.saveSettings(dlg.values, function (ok) { if (ok) dlg.open = false })
        }
    ]
}
