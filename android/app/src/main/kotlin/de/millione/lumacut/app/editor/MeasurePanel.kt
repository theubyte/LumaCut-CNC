package de.millione.lumacut.app.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.IconBtn
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.core.MeasureEval

/** One short sentence for what the next touch does. */
fun measureHint(mode: MeasureMode, points: Int, firstElement: Boolean): String = when (mode) {
    MeasureMode.DISTANCE -> if (points == 0) "Ersten Punkt antippen oder ziehen – die Lupe zeigt, was gefangen wird" else "Zweiten Punkt antippen …"
    MeasureMode.ANGLE -> when (points) {
        0 -> "Ersten Punkt (Ende des ersten Schenkels) antippen"
        1 -> "Scheitelpunkt antippen"
        else -> "Ende des zweiten Schenkels antippen …"
    }
    MeasureMode.GAP -> if (!firstElement) "Erstes Element antippen" else "Zweites Element antippen …"
    MeasureMode.INFO -> "Ein Element antippen: Maße, Umfang, Fläche, Laserweg"
    MeasureMode.EDGES -> "Ein Element antippen: Abstand zu allen vier Rändern"
}

/** Mode bar on top of the canvas: what to measure, and snapping on/off. */
@Composable
fun MeasureBar(editor: EditorViewModel, modifier: Modifier = Modifier) {
    val mode by editor.measureMode.collectAsStateWithLifecycle()
    val snap by editor.snapOn.collectAsStateWithLifecycle()
    Row(modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        for (m in MeasureMode.entries) Pill(m.label, m == mode) { editor.setMeasureMode(m) }
        Pill(if (snap) "Fangen: an" else "Fangen: aus", snap) { editor.setSnap(!snap) }
    }
}

@Composable
private fun Pill(text: String, on: Boolean, onClick: () -> Unit) {
    Text(
        text, style = LcTypography.labelLarge, color = if (on) Lc.accent else Lc.text, maxLines = 1,
        modifier = Modifier.heightIn(min = 44.dp).clip(RoundedCornerShape(14.dp))
            .background(if (on) Lc.accentSoft else Lc.surface).border(1.dp, if (on) Lc.accent else Lc.line, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 12.dp),
    )
}

/** Side panel while measuring: hint, the list of measurements (tap = mark and copy, bin = delete) and "delete all". */
@Composable
fun MeasurePanel(editor: EditorViewModel, modifier: Modifier) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val list by editor.measurements.collectAsStateWithLifecycle()
    val selected by editor.measureSelected.collectAsStateWithLifecycle()
    val mode by editor.measureMode.collectAsStateWithLifecycle()
    val points by editor.pendingPoints.collectAsStateWithLifecycle()
    val firstEl by editor.pendingElement.collectAsStateWithLifecycle()
    val clipboard = LocalClipboardManager.current
    val views = remember(doc, list) { list.map { it to MeasureEval.eval(it, doc) } }
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        LcCard(padding = 16.dp) {
            Text("Messen", style = LcTypography.titleLarge)
            Spacer(Modifier.height(6.dp))
            SmallText(measureHint(mode, points.size, firstEl != null), Lc.text)
            Spacer(Modifier.height(6.dp))
            SmallText("Maße sind nur Anzeige: sie werden weder gelasert noch im Auftrag oder Projekt gespeichert. Millimeter, Nullpunkt oben links.")
        }
        if (views.isEmpty()) SmallText("Noch keine Messung.", Lc.faint)
        for ((m, v) in views.asReversed()) {
            val on = m.id == selected
            LcCard(
                Modifier.clickable {
                    editor.selectMeasurement(m.id)
                    if (v.copy.isNotBlank()) { clipboard.setText(AnnotatedString(v.copy)); editor.notify("Kopiert: ${v.copy}") }
                },
                padding = 14.dp, accent = if (on) Lc.accent else null,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(v.title + if (v.stale) " · veraltet" else "", style = LcTypography.titleMedium, color = if (v.stale) Lc.faint else Lc.text, modifier = Modifier.weight(1f))
                    IconBtn(LcIcons.trash, "Messung löschen", { editor.removeMeasurement(m.id) }, tint = Lc.bad)
                }
                for (line in v.lines) SmallText(line, if (v.stale) Lc.faint else Lc.muted)
            }
        }
        if (views.isNotEmpty()) LcButton("Alle löschen", { editor.clearMeasurements() }, Modifier.fillMaxWidth(), kind = BtnKind.GHOST)
    }
}
