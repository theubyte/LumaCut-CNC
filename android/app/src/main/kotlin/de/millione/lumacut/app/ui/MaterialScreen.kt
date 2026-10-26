package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.Limits
import de.millione.lumacut.core.Material
import kotlin.math.roundToInt

@Composable
fun MaterialScreen(editor: EditorViewModel) {
    val materials by editor.materials.collectAsStateWithLifecycle()
    var editing by remember { mutableStateOf<Material?>(null) }
    var confirm by rememberConfirm()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Materialbibliothek", style = LcTypography.headlineSmall)
                SmallText("Werte im Editor über „Material …“ auf eine Ebene übernehmen. Startwerte – jedes Material am eigenen Laser testen.")
            }
            LcButton("Neues Material", {
                editing = Material(name = "", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 80.0, speed = 400.0)
            }, icon = LcIcons.plus, kind = BtnKind.PRIMARY)
        }
        Spacer(Modifier.height(16.dp))
        LazyVerticalGrid(GridCells.Adaptive(300.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(materials, key = { it.id }) { m ->
                Column(
                    Modifier.clip(RoundedCornerShape(18.dp)).background(Lc.surface).border(1.dp, Lc.line, RoundedCornerShape(18.dp))
                        .clickable { editing = m }.padding(18.dp)
                ) {
                    Eyebrow(m.process)
                    Text("${m.name} · ${formatMm(m.thicknessMm)} mm", style = LcTypography.titleLarge)
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Tile("Leistung", "${m.powerPct.roundToInt()} %", Modifier.weight(1f))
                        Tile("Tempo", "${m.speed.roundToInt()}", Modifier.weight(1f))
                        Tile(if (m.mode == LayerMode.FILL) "Abstand" else "Durchg.", if (m.mode == LayerMode.FILL) "${m.intervalMm} mm" else "${m.effectivePasses}×", Modifier.weight(1f))
                    }
                    if (m.depthPerPassMm > 0 || m.zStepMm > 0) {
                        Spacer(Modifier.height(6.dp))
                        SmallText(buildString {
                            if (m.depthPerPassMm > 0) append("%.2f mm pro Durchgang".format(m.depthPerPassMm))
                            if (m.zStepMm > 0) { if (isNotEmpty()) append(" · "); append("Fokus −%.2f mm je Durchgang".format(m.zStepMm)) }
                        }, Lc.faint)
                    }
                }
            }
        }
    }
    editing?.let { m ->
        MaterialDialog(m, onDismiss = { editing = null },
            onSave = { editor.saveMaterial(it); editing = null },
            onDelete = { editing = null; confirm = Confirm("Material löschen?", "${m.name} ${m.thicknessMm} mm · ${m.process}", "Löschen", true) { editor.deleteMaterial(m.id) } })
    }
    ConfirmDialog(confirm) { confirm = null }
}

private fun formatMm(v: Double) = if (v % 1.0 == 0.0) v.roundToInt().toString() else v.toString()

@Composable
private fun MaterialDialog(m: Material, onDismiss: () -> Unit, onSave: (Material) -> Unit, onDelete: () -> Unit) {
    var name by remember { mutableStateOf(m.name) }
    var thick by remember { mutableStateOf(m.thicknessMm.toString()) }
    var process by remember { mutableStateOf(m.process) }
    var mode by remember { mutableStateOf(m.mode) }
    var power by remember { mutableStateOf(m.powerPct.toString()) }
    var speed by remember { mutableStateOf(m.speed.toString()) }
    var passes by remember { mutableStateOf(m.passes.toString()) }
    var interval by remember { mutableStateOf(m.intervalMm.toString()) }
    var depth by remember { mutableStateOf(m.depthPerPassMm.toString()) }
    var zStep by remember { mutableStateOf(m.zStepMm.toString()) }
    fun d(s: String) = s.replace(',', '.').toDoubleOrNull()
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text(if (m.name.isBlank()) "Neues Material" else "Material bearbeiten", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextInput("Material", name, { name = it }, Modifier.weight(2f))
                    NumberField("Stärke", thick, { thick = it }, Modifier.weight(1f), "mm")
                }
                TextInput("Bearbeitung (z. B. Schneiden, Gravieren)", process, { process = it }, Modifier.fillMaxWidth())
                Segmented(listOf(LayerMode.LINE to "Linie / Schneiden", LayerMode.FILL to "Füllen / Gravieren"), mode, { mode = it })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Leistung", power, { power = it }, Modifier.weight(1f), "%")
                    NumberField("Tempo", speed, { speed = it }, Modifier.weight(1f), "mm/min")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Durchgänge", passes, { passes = it }, Modifier.weight(1f))
                    NumberField("Zeilenabstand", interval, { interval = it }, Modifier.weight(1f), "mm")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Tiefe/Durchgang", depth, { depth = it }, Modifier.weight(1f), "mm")
                    NumberField("Z-Absenkung/Durchg.", zStep, { zStep = it }, Modifier.weight(1f), "mm")
                }
                SmallText("Mit Tiefe pro Durchgang ergeben sich die Durchgänge aus der Stärke. Die Z-Absenkung bleibt insgesamt ≤ 3 mm.")
            }
        },
        confirmButton = {
            val valid = name.isNotBlank() && d(thick)?.let { it in Limits.THICKNESS } == true && d(power)?.let { it in Limits.POWER } == true &&
                d(speed)?.let { it in Limits.SPEED } == true && passes.toIntOrNull()?.let { it in Limits.PASSES } == true &&
                d(interval)?.let { it in 0.03..2.0 } == true && d(depth)?.let { it in Limits.DEPTH_PER_PASS } == true &&
                d(zStep)?.let { it in Limits.Z_STEP } == true
            LcButton("Speichern", {
                onSave(m.copy(name = name.trim(), thicknessMm = d(thick)!!, process = process.trim().ifEmpty { "Schneiden" }, mode = mode,
                    powerPct = d(power)!!, speed = d(speed)!!, passes = passes.toInt(), intervalMm = d(interval)!!,
                    depthPerPassMm = d(depth)!!, zStepMm = d(zStep)!!))
            }, kind = BtnKind.PRIMARY, enabled = valid)
        },
        dismissButton = {
            Row {
                if (m.name.isNotBlank()) TextButton(onClick = onDelete) { Text("Löschen", color = Lc.bad) }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) }
            }
        },
    )
}
