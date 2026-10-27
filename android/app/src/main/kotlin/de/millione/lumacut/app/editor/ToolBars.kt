package de.millione.lumacut.app.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.core.ShapeKind

/** Small choice chip for the option bar over the canvas. */
@Composable
private fun Chip(text: String, on: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    Text(
        text, style = LcTypography.labelLarge, color = if (!enabled) Lc.faint else if (on) Lc.accent else Lc.text, maxLines = 1,
        modifier = Modifier.heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp))
            .background(if (on) Lc.accentSoft else Lc.surface).border(1.dp, if (on) Lc.accent else Lc.line, RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp),
    )
}

/** Options of the current tool of the left bar (shape kind, sides, curve finish, layer to paint, node delete). */
@Composable
fun ToolOptions(editor: EditorViewModel, tool: Tool, modifier: Modifier = Modifier) {
    val kind by editor.shapeKind.collectAsStateWithLifecycle()
    val sides by editor.polygonSides.collectAsStateWithLifecycle()
    val curve by editor.curve.collectAsStateWithLifecycle()
    val doc by editor.doc.collectAsStateWithLifecycle()
    val active by editor.activeLayer.collectAsStateWithLifecycle()
    val stamp by editor.stamp.collectAsStateWithLifecycle()
    val node by editor.activeNode.collectAsStateWithLifecycle()
    Row(modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        when (tool) {
            Tool.SHAPE -> for (k in ShapeKind.entries) Chip(k.label, k == kind) { editor.setShapeKind(k) }
            Tool.POLYGON -> for (n in listOf(3, 4, 5, 6, 8, 10, 12)) Chip("$n Ecken", n == sides) { editor.setPolygonSides(n) }
            Tool.CURVE -> {
                Chip("Fertig (offen)", false, curve.size >= 2) { editor.finishCurve(false) }
                Chip("Fertig (geschlossen)", false, curve.size >= 3) { editor.finishCurve(true) }
                Chip("Letzten Punkt weg", false, curve.isNotEmpty()) { editor.undoCurvePoint() }
                Chip("Verwerfen", false, curve.isNotEmpty()) { editor.cancelCurve() }
            }
            Tool.PAINT -> for (name in listOf("Gravieren", "Linie", "Schneiden")) doc.layers.firstOrNull { it.name == name }?.let { l ->
                Chip(if (name == "Linie") "Markieren" else name, l.id == active) { editor.setActiveLayer(l.id) }
            }
            Tool.STAMP -> Chip(if (stamp.isEmpty()) "Keine Vorlage – erst auswählen" else "Vorlage: ${stamp.size} Element(e)", stamp.isNotEmpty()) {}
            Tool.NODES -> Chip("Punkt löschen", false, node != null) { editor.deleteActiveNode() }
            else -> {}
        }
    }
}
