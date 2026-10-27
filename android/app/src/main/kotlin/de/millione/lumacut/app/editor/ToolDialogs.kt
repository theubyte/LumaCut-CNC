package de.millione.lumacut.app.editor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.ui.BarBtn
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.core.Align
import de.millione.lumacut.core.BoxSpec

private fun num(s: String) = s.replace(',', '.').toDoubleOrNull()

@Composable
private fun ToolDialog(title: String, action: String, valid: Boolean, onDismiss: () -> Unit, onApply: () -> Unit, content: @Composable () -> Unit) =
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text(title, style = LcTypography.titleLarge) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { content() } },
        confirmButton = { LcButton(action, { onApply(); onDismiss() }, kind = BtnKind.PRIMARY, enabled = valid) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )

/** Holding tabs: a few small uncut bridges per closed shape so parts stay in the sheet. */
@Composable
fun TabsDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var count by remember { mutableStateOf("2") }
    var width by remember { mutableStateOf("0.5") }
    val valid = count.toIntOrNull()?.let { it in 1..20 } == true && num(width)?.let { it in 0.1..5.0 } == true
    ToolDialog("Haltestege", "Stege setzen", valid, onDismiss, {
        val n = editor.tabsSelected(count.toInt(), num(width)!!)
        editor.notify(if (n > 0) "Haltestege an $n Element(en) gesetzt" else "Keine geschlossene Form groß genug für Stege", n == 0)
    }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Stege pro Form", count, { count = it }, Modifier.weight(1f))
            NumberField("Stegbreite", width, { width = it }, Modifier.weight(1f), "mm")
        }
        SmallText("Die Teile bleiben nach dem Schneiden in der Platte hängen und fallen nicht durch. Zum Lösen kurz herausbrechen. " +
            "Für 3 mm Holz mit 10 W reichen 0,3–0,6 mm.", Lc.faint)
    }
}

/** Copies on a circle around a centre below the selection. */
@Composable
fun CircularArrayDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var count by remember { mutableStateOf("6") }
    var radius by remember { mutableStateOf("50") }
    var rotate by remember { mutableStateOf(true) }
    val valid = count.toIntOrNull()?.let { it in 2..72 } == true && num(radius)?.let { it in 1.0..400.0 } == true
    ToolDialog("Kreisanordnung", "Anordnen", valid, onDismiss, {
        val left = editor.circularArray(count.toInt(), num(radius)!!, rotate)
        editor.notify(if (left > 0) "$left Kopien passen nicht in den Arbeitsbereich und fehlen" else "Kopien im Kreis angelegt", left > 0)
    }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Anzahl gesamt", count, { count = it }, Modifier.weight(1f))
            NumberField("Radius", radius, { radius = it }, Modifier.weight(1f), "mm")
        }
        Segmented(listOf(true to "Mitdrehen", false to "Nur verschieben"), rotate, { rotate = it }, Modifier.fillMaxWidth())
        SmallText("Die Auswahl ist das oberste Element; der Kreismittelpunkt liegt um den Radius darunter.", Lc.faint)
    }
}

/** Finger-jointed box maker. */
@Composable
fun BoxDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var w by remember { mutableStateOf("100") }
    var d by remember { mutableStateOf("80") }
    var h by remember { mutableStateOf("60") }
    var t by remember { mutableStateOf(editor.cutThickness().let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() }) }
    var finger by remember { mutableStateOf("10") }
    var closed by remember { mutableStateOf(false) }
    val tv = num(t)
    val valid = listOf(w, d, h).all { s -> num(s)?.let { it in 20.0..340.0 } == true } && tv != null && tv in 0.5..10.0 &&
        num(finger)?.let { it in 2.0..50.0 } == true && listOf(w, d, h).all { num(it)!! > 4 * tv }
    ToolDialog("Box mit Fingerzinken", "Box erzeugen", valid, onDismiss, {
        editor.addBox(BoxSpec(num(w)!!, num(d)!!, num(h)!!, tv!!, num(finger)!!, closed))
    }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Breite", w, { w = it }, Modifier.weight(1f), "mm")
            NumberField("Tiefe", d, { d = it }, Modifier.weight(1f), "mm")
            NumberField("Höhe", h, { h = it }, Modifier.weight(1f), "mm")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Materialstärke", t, { t = it }, Modifier.weight(1f), "mm")
            NumberField("Zinkenbreite", finger, { finger = it }, Modifier.weight(1f), "mm")
        }
        Segmented(listOf(false to "Oben offen", true to "Mit Deckel"), closed, { closed = it }, Modifier.fillMaxWidth())
        SmallText("Außenmaße. Die Teile landen auf der Ebene „Schneiden“, passt nicht alles, geht es auf weiteren Platten weiter. " +
            "Materialstärke genau messen – davon hängt die Passung ab.", Lc.faint)
    }
}

/** Align / distribute / mirror buttons for the selection card. With one element or group it aligns to the work area. */
@Composable
fun AlignRows(editor: EditorViewModel, units: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        for ((mode, icon) in listOf(Align.Mode.LEFT to LcIcons.alignLeft, Align.Mode.CENTER_X to LcIcons.alignCenterX,
                Align.Mode.RIGHT to LcIcons.alignRight, Align.Mode.TOP to LcIcons.alignTop, Align.Mode.CENTER_Y to LcIcons.alignCenterY,
                Align.Mode.BOTTOM to LcIcons.alignBottom))
            BarBtn(icon, null, { editor.alignSelected(mode) }, Modifier.weight(1f),
                description = (if (units >= 2) "Ausrichten " else "An Arbeitsfläche ausrichten ") + mode.label)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        BarBtn(LcIcons.mirrorH, null, { editor.mirrorSelected(true) }, Modifier.weight(1f), description = "Waagrecht spiegeln")
        BarBtn(LcIcons.mirrorV, null, { editor.mirrorSelected(false) }, Modifier.weight(1f), description = "Senkrecht spiegeln")
        BarBtn(LcIcons.distributeH, null, { editor.distributeSelected(true) }, Modifier.weight(1f), enabled = units >= 3, description = "Waagrecht verteilen")
        BarBtn(LcIcons.distributeV, null, { editor.distributeSelected(false) }, Modifier.weight(1f), enabled = units >= 3, description = "Senkrecht verteilen")
    }
    SmallText(if (units >= 2) "Ausrichten zueinander · Spiegeln · Verteilen (ab 3)" else "Ausrichten an der Arbeitsfläche · Spiegeln", Lc.faint)
}

