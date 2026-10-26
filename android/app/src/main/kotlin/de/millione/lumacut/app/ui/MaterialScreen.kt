package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
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
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.Limits
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.MaterialGroup
import de.millione.lumacut.core.grouped
import kotlin.math.roundToInt

private val PROCESSES = listOf("Schneiden", "Gravieren", "Markieren")

/** Step 1: pick the material. The Pi database is the source; values go onto the motif's layers. */
@Composable
fun MaterialScreen(machine: MachineViewModel, editor: EditorViewModel, onNext: () -> Unit) {
    val state by machine.materials.collectAsStateWithLifecycle()
    val chosen by editor.materialKey.collectAsStateWithLifecycle()
    var query by remember { mutableStateOf("") }
    var advanced by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Pair<Material, Boolean>?>(null) }
    var confirm by rememberConfirm()
    val groups = state.items.grouped(query)
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f)) {
                Text("1 · Material wählen", style = LcTypography.headlineSmall)
                SmallText("Leistung, Tempo und Durchgänge setzt die App danach selbst.")
            }
            TextInput("Suchen", query, { query = it }, Modifier.width(260.dp))
            IconBtn(LcIcons.refresh, "Liste neu laden", { machine.refreshMaterials() })
            val picked = groups.firstOrNull { it.key == chosen }
            LcButton("Weiter: Motiv", onNext, icon = LcIcons.right, kind = BtnKind.PRIMARY, enabled = picked != null || chosen != null, big = true)
        }
        if (!state.fromPi) Banner("Kein Kontakt zum Pi – das ist die zuletzt gespeicherte Liste. Verbindung unter Einstellungen prüfen.", Lc.info)
        if (groups.isEmpty()) SmallText("Kein Material gefunden. Anderen Suchbegriff versuchen.")
        LazyVerticalGrid(GridCells.Adaptive(300.dp), Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(groups, key = { it.key }) { g ->
                val on = g.key == chosen
                Column(
                    Modifier.clip(RoundedCornerShape(18.dp)).background(if (on) Lc.accentSoft else Lc.surface)
                        .border(if (on) 2.dp else 1.dp, if (on) Lc.accent else Lc.line, RoundedCornerShape(18.dp))
                        .clickable { editor.selectMaterial(g) }.padding(18.dp)
                ) {
                    Text(g.name, style = LcTypography.titleLarge)
                    Text("${formatMm(g.thicknessMm)} mm", style = LcTypography.titleMedium, color = Lc.muted)
                    Spacer(Modifier.height(10.dp))
                    SmallText(g.processes.joinToString(" · "), if (on) Lc.accent else Lc.faint)
                    if (advanced) {
                        Spacer(Modifier.height(10.dp))
                        for (m in g.entries) Row(
                            Modifier.fillMaxWidth().heightIn(min = Lc.touch).clickable { editing = m to false },
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("${m.process}: ${m.powerPct.roundToInt()} % · ${m.speed.roundToInt()} mm/min · ${m.effectivePasses}×",
                                style = LcTypography.bodyMedium, modifier = Modifier.weight(1f))
                            Text("ändern", style = LcTypography.labelMedium, color = Lc.accent)
                        }
                    }
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            LcButton(if (advanced) "Erweitert ausblenden" else "Erweitert: Materialwerte bearbeiten", { advanced = !advanced }, kind = BtnKind.GHOST)
            if (advanced) LcButton("Neues Material", {
                editing = Material(id = "", name = "", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 80.0, speed = 400.0) to true
            }, icon = LcIcons.plus)
            SmallText("Startwerte – jedes Material am eigenen Laser testen. Änderungen gelten auch für Windows-App und Web-Oberfläche.", Lc.faint)
        }
    }
    editing?.let { (m, isNew) ->
        MaterialDialog(m, isNew, onDismiss = { editing = null },
            onSave = { machine.saveMaterial(it, isNew); editing = null },
            onDelete = { editing = null; confirm = Confirm("Material löschen?", "${m.name} ${formatMm(m.thicknessMm)} mm · ${m.process}", "Löschen", true) { machine.deleteMaterial(m.id) } })
    }
    ConfirmDialog(confirm) { confirm = null }
}

private fun formatMm(v: Double) = if (v % 1.0 == 0.0) v.roundToInt().toString() else v.toString()

@Composable
private fun MaterialDialog(m: Material, isNew: Boolean, onDismiss: () -> Unit, onSave: (Material) -> Unit, onDelete: () -> Unit) {
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
        title = { Text(if (isNew) "Neues Material" else "Material bearbeiten", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextInput("Material", name, { name = it }, Modifier.weight(2f))
                    NumberField("Stärke", thick, { thick = it }, Modifier.weight(1f), "mm")
                }
                Segmented(PROCESSES.map { it to it }, process, { p ->
                    process = p
                    mode = if (p == "Gravieren") LayerMode.FILL else LayerMode.LINE
                })
                Segmented(listOf(LayerMode.LINE to "Linie", LayerMode.FILL to "Füllen"), mode, { mode = it })
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
                onSave(m.copy(name = name.trim(), thicknessMm = d(thick)!!, process = process, mode = mode,
                    powerPct = d(power)!!, speed = d(speed)!!, passes = passes.toInt(), intervalMm = d(interval)!!,
                    depthPerPassMm = d(depth)!!, zStepMm = d(zStep)!!))
            }, kind = BtnKind.PRIMARY, enabled = valid)
        },
        dismissButton = {
            Row {
                if (!isNew && !m.builtin) TextButton(onClick = onDelete) { Text("Löschen", color = Lc.bad) }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) }
            }
        },
    )
}
