import QtQuick
import QtQuick.Layouts
import LumaCut

Item {
    objectName: "view-Platine"
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.sp6, 560)
        spacing: Theme.sp2
        LcText { text: "Platine: nächste Etappe"; font.family: Theme.fontDisplay; font.pixelSize: Theme.fs2xl; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
        LcText { text: "Gerber und Excellon, Isolationsbahnen, Lötstopp, Passmarken und der Prozess-Assistent werden nach der Bedienung nativ gebaut. Bis dahin steht diese Ansicht nur als Platzhalter hier: Es gibt noch keine Funktion dahinter."; kind: "muted"; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
    }
}
