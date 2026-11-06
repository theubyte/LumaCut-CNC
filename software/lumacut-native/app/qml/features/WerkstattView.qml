import QtQuick
import QtQuick.Layouts
import LumaCut

Item {
    objectName: "view-Werkstatt"
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.sp6, 560)
        spacing: Theme.sp2
        LcText { text: "Werkstatt: nächste Etappe"; font.family: Theme.fontDisplay; font.pixelSize: Theme.fs2xl; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
        LcText { text: "Materialtest-Raster, Fotogravur, Stempel, Boxen, Zahnrad, Seriennummern, QR-Codes und Vorlagen werden nach der Bedienung nativ gebaut. Bis dahin gibt es hier noch keine Funktion. Den Materialtest mit Kamera findest du unter Maschine, Kalibrieren."; kind: "muted"; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
    }
}
