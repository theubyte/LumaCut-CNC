package de.millione.lumacut.app.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.IconBtn
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.Limits
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.grouped
import java.util.Locale
import kotlin.math.roundToInt

/** What the operator calls a layer: the standard "Linie" layer is "Markieren" everywhere in the app. */
internal fun Layer.label() = if (name == "Linie") "Markieren" else name

private fun Layer.values() = buildString {
    append("${powerPct.roundToInt()} % · ${speed.roundToInt()} mm/min")
    if (passes > 1) append(" · ${passes}×")
}

private fun fmtMm(v: Double) = if (v % 1.0 == 0.0) v.toInt().toString() else "%.1f".format(Locale.GERMANY, v)

/**
 * The laser part of the inspector, in the order a job is set up: which
 * material lies on the bed, what the laser does with the selection, and the
 * layers (= processing order) with their values at a glance. Tapping a
 * layer opens its settings; it never moves the selection by itself.
 */
@Composable
internal fun LaserCard(editor: EditorViewModel, doc: Document, sel: List<Element>, active: String) {
    val materials by editor.materials.collectAsStateWithLifecycle()
    val key by editor.materialKey.collectAsStateWithLifecycle()
    var editing by remember { mutableStateOf<String?>(null) }
    var materialMenu by remember { mutableStateOf(false) }
    val focus = sel.firstOrNull()?.layerId ?: active
    LcCard(padding = 14.dp) {
        Text("Laser", style = LcTypography.titleLarge)
        Spacer(Modifier.height(10.dp))

        // 1. material
        SmallText("Material auf dem Bett", Lc.faint)
        Spacer(Modifier.height(4.dp))
        Box {
            val current = key?.split("|")?.let { p -> "${p[0]} · ${fmtMm(p.getOrNull(1)?.toDoubleOrNull() ?: 0.0)} mm" }
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Lc.surface2).border(1.dp, Lc.line2, RoundedCornerShape(12.dp))
                    .clickable { materialMenu = true }.padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Icon(LcIcons.material, null, tint = Lc.accent, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(10.dp))
                Text(current ?: "Material wählen …", style = LcTypography.titleMedium, color = if (current == null) Lc.muted else Lc.text,
                    modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Icon(LcIcons.down, null, tint = Lc.muted, modifier = Modifier.size(18.dp))
            }
            DropdownMenu(materialMenu, { materialMenu = false }, containerColor = Lc.surface2, modifier = Modifier.heightIn(max = 420.dp)) {
                val groups = materials.grouped()
                if (groups.isEmpty()) DropdownMenuItem(text = { SmallText("Keine Materialien – Pi verbunden?") }, onClick = {}, enabled = false)
                for (g in groups) DropdownMenuItem(
                    text = { Column { Text("${g.name} · ${fmtMm(g.thicknessMm)} mm", style = LcTypography.titleMedium); SmallText(g.processes.joinToString(" · "), Lc.faint) } },
                    onClick = { materialMenu = false; editor.selectMaterial(g) })
            }
        }
        SmallText("Setzt die Werte aller Ebenen auf einmal.", Lc.faint)

        // 2. what the laser does with the selection / new shapes
        Spacer(Modifier.height(14.dp))
        Text("Was soll der Laser tun?", style = LcTypography.titleMedium)
        Spacer(Modifier.height(6.dp))
        val byName = doc.layers.associateBy { it.name }
        // Projects without the three standard layers (material test, imports) offer their own layers instead of an empty bar.
        val options = listOf("Gravieren", "Linie", "Schneiden").mapNotNull { byName[it] }.map { it.id to it.label() }
            .ifEmpty { doc.layers.filter { l -> doc.elements.any { it.layerId == l.id } }.ifEmpty { doc.layers }.take(4).map { it.id to it.label() } }
        Segmented(options, focus, { editor.setActiveLayer(it) }, Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()))
        Spacer(Modifier.height(4.dp))
        SmallText(if (sel.isNotEmpty()) "Gilt für die Auswahl (${sel.size})." else "Gilt für neue Formen – zum Ändern erst etwas antippen.", Lc.faint)

        // 3. layers
        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Ebenen", style = LcTypography.titleMedium)
                SmallText("von oben nach unten gelasert · antippen = Werte", Lc.faint)
            }
            IconBtn(LcIcons.plus, "Ebene hinzufügen", { editor.addLayer(); editing = editor.activeLayer.value })
        }
        Spacer(Modifier.height(8.dp))
        for (layer in doc.layers) {
            val count = doc.elements.count { it.layerId == layer.id }
            LayerLine(editor, layer, layer.id == focus, count) { editing = layer.id }
        }
    }
    editing?.let { id -> doc.layer(id)?.let { LayerDialog(editor, it, materials, sel, doc.elements.any { e -> e.layerId == id && e.isImage }) { editing = null } } ?: run { editing = null } }
}

@Composable
private fun LayerLine(editor: EditorViewModel, layer: Layer, focused: Boolean, count: Int, onOpen: () -> Unit) {
    val color = Color(layer.color.toInt())
    val off = !layer.visible || !layer.output
    Row(
        Modifier.fillMaxWidth().padding(bottom = 6.dp).clip(RoundedCornerShape(12.dp))
            .background(if (focused) Lc.surface3 else Lc.surface2)
            .border(1.dp, if (focused) color.copy(alpha = .8f) else Lc.line, RoundedCornerShape(12.dp))
            .clickable(onClick = onOpen).padding(start = 10.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(width = 5.dp, height = 34.dp).clip(RoundedCornerShape(3.dp)).background(color.copy(alpha = if (off) .3f else 1f)))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(layer.label(), style = LcTypography.titleMedium, fontWeight = FontWeight.SemiBold, color = if (off) Lc.faint else Lc.text,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                Spacer(Modifier.width(6.dp))
                Text(if (layer.mode == LayerMode.FILL) "Füllen" else "Linie", style = LcTypography.labelSmall, color = Lc.muted,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Lc.bg).padding(horizontal = 6.dp, vertical = 2.dp))
            }
            SmallText(when {
                !layer.output -> "wird nicht gelasert"
                else -> layer.values()
            } + " · " + when (count) { 0 -> "leer"; 1 -> "1 Teil"; else -> "$count Teile" }, if (off) Lc.faint else Lc.muted)
            layer.materialName?.let { SmallText("aus „$it${if (layer.thicknessMm > 0) " " + fmtMm(layer.thicknessMm) + " mm" else ""}“", Lc.faint) }
        }
        IconBtn(if (layer.visible) LcIcons.eye else LcIcons.eyeOff, if (layer.visible) "Ausblenden" else "Einblenden",
            { editor.updateLayer(layer.id) { it.copy(visible = !it.visible) } }, tint = if (layer.visible) Lc.muted else Lc.faint)
        Icon(LcIcons.right, null, tint = Lc.faint, modifier = Modifier.size(18.dp))
    }
}

/** Keeps the per-pass focus drop within [Limits.MAX_FOCUS_DROP_MM]. */
internal fun Layer.withSafeZStep(): Layer =
    if (passes > 1) copy(zStepMm = zStepMm.coerceIn(0.0, minOf(Limits.Z_STEP.endInclusive, Limits.MAX_FOCUS_DROP_MM / (passes - 1)))) else copy(zStepMm = 0.0)

/**
 * Settings of one layer, only what fits its kind: line or fill, the three
 * laser values, engraving details for fills, depth for several passes, a
 * material to take the values from, and order / delete.
 */
@Composable
private fun LayerDialog(editor: EditorViewModel, layer: Layer, materials: List<Material>, sel: List<Element>, hasImage: Boolean, onClose: () -> Unit) {
    var materialMenu by remember { mutableStateOf(false) }
    val maxFeed = editor.motion.maxFeed
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        LcCard(Modifier.padding(12.dp).widthIn(max = 600.dp).fillMaxWidth().heightIn(max = 760.dp), padding = 20.dp) {
            Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(18.dp).clip(CircleShape).background(Color(layer.color.toInt())))
                    Spacer(Modifier.width(10.dp))
                    Text("Ebene „${layer.label()}“", style = LcTypography.headlineSmall, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("lasern", style = LcTypography.bodyMedium, color = Lc.muted)
                    Spacer(Modifier.width(8.dp))
                    Switch(layer.output, { on -> editor.updateLayer(layer.id) { it.copy(output = on) } })
                }
                if (layer.name !in setOf("Gravieren", "Linie", "Schneiden"))
                    TextInput("Name", layer.name, { n -> editor.updateLayer(layer.id, "name") { it.copy(name = n) } }, Modifier.fillMaxWidth())

                Section("Art")
                Segmented(listOf(LayerMode.LINE to "Linie (markieren, schneiden)", LayerMode.FILL to "Fläche füllen (gravieren)"), layer.mode,
                    { m -> editor.updateLayer(layer.id) { it.copy(mode = m) } }, Modifier.fillMaxWidth())

                Section("Laserwerte")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Num("Leistung", layer.powerPct, Modifier.weight(1f), "%") { v -> editor.updateLayer(layer.id, "power") { it.copy(powerPct = v.coerceIn(Limits.POWER)) } }
                    Num("Tempo", layer.speed, Modifier.weight(1f), "mm/min") { v -> editor.updateLayer(layer.id, "speed") { it.copy(speed = v.coerceIn(1.0, maxFeed)) } }
                    Num("Durchgänge", layer.passes.toDouble(), Modifier.weight(0.8f), "×") { v ->
                        editor.updateLayer(layer.id, "passes") { it.copy(passes = v.toInt().coerceIn(Limits.PASSES)).withSafeZStep() } }
                }
                SmallText("Tempo höchstens %.0f mm/min (Maschine → Kalibrieren → Bewegung).".format(maxFeed), Lc.faint)

                if (layer.mode == LayerMode.FILL || hasImage) {
                    Section("Gravur")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Num("Zeilenabstand", layer.intervalMm, Modifier.weight(1f)) { v -> editor.updateLayer(layer.id, "interval") { it.copy(intervalMm = v.coerceIn(0.03, 2.0)) } }
                        if (hasImage) Num("Min. Leistung (Bild)", layer.minPowerPct, Modifier.weight(1f), "%") { v ->
                            editor.updateLayer(layer.id, "minpower") { it.copy(minPowerPct = v.coerceIn(Limits.POWER)) } }
                    }
                    SmallText("Anlauf je Zeile automatisch: %.1f mm bei diesem Tempo (damit die Ränder nicht dunkler werden).".format(Locale.GERMANY,
                        maxOf(layer.overscanMm, editor.motion.runUp(layer.speed))), Lc.faint)
                }

                if (layer.passes > 1 || layer.thicknessMm > 0) {
                    Section("Tiefe (mehrere Durchgänge)")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Num("Materialstärke", layer.thicknessMm, Modifier.weight(1f)) { v -> editor.updateLayer(layer.id, "thick") { l ->
                            val t = v.coerceIn(Limits.THICKNESS)
                            (if (l.depthPerPassMm > 0 && t > 0) l.copy(thicknessMm = t, passes = Document.passesFor(t, l.depthPerPassMm)) else l.copy(thicknessMm = t)).withSafeZStep()
                        } }
                        Num("Tiefe je Durchgang", layer.depthPerPassMm, Modifier.weight(1f)) { v -> editor.updateLayer(layer.id, "depth") { l ->
                            val d = v.coerceIn(Limits.DEPTH_PER_PASS)
                            (if (d > 0 && l.thicknessMm > 0) l.copy(depthPerPassMm = d, passes = Document.passesFor(l.thicknessMm, d)) else l.copy(depthPerPassMm = d)).withSafeZStep()
                        } }
                        Num("Fokus tiefer je Durchgang", layer.zStepMm, Modifier.weight(1f)) { v -> editor.updateLayer(layer.id, "zstep") { it.copy(zStepMm = v).withSafeZStep() } }
                    }
                    SmallText(when {
                        layer.passes <= 1 -> "Ein Durchgang: kein Nachfokussieren."
                        layer.zStepMm > 0 -> "Fokus sinkt je Durchgang um %.2f mm, insgesamt %.2f mm (höchstens %.0f mm), danach zurück.".format(Locale.GERMANY, layer.zStepMm, layer.focusDropMm, Limits.MAX_FOCUS_DROP_MM)
                        else -> "Alle ${layer.passes} Durchgänge auf derselben Fokushöhe."
                    }, Lc.faint)
                }

                Section("Werte aus Material")
                Box {
                    LcButton(layer.materialName?.let { "Aus „$it“ – anderes wählen …" } ?: "Material wählen …", { materialMenu = true }, icon = LcIcons.material)
                    DropdownMenu(materialMenu, { materialMenu = false }, containerColor = Lc.surface2, modifier = Modifier.heightIn(max = 420.dp)) {
                        // matching processes first: fills want engraving entries, lines marking and cutting
                        val fits = { m: Material -> (m.mode == layer.mode) }
                        val sorted = materials.sortedWith(compareBy<Material>({ !fits(it) }, { it.name.lowercase() }, { it.thicknessMm }))
                        if (sorted.isEmpty()) DropdownMenuItem(text = { SmallText("Keine Materialien – Pi verbunden?") }, onClick = {}, enabled = false)
                        for (m in sorted) DropdownMenuItem(
                            text = { Column {
                                Text("${m.name} · ${fmtMm(m.thicknessMm)} mm · ${m.process}", style = LcTypography.titleMedium, color = if (fits(m)) Lc.text else Lc.muted)
                                SmallText("${m.powerPct.roundToInt()} % · ${m.speed.roundToInt()} mm/min" + if (m.effectivePasses > 1) " · ${m.effectivePasses}×" else "", Lc.faint)
                            } },
                            onClick = { materialMenu = false; editor.applyMaterial(layer.id, m) })
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
            HorizontalDivider(color = Lc.line)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (sel.isNotEmpty() && sel.any { it.layerId != layer.id })
                    LcButton("Auswahl hierher (${sel.size})", { editor.setActiveLayer(layer.id) }, icon = LcIcons.layers)
                IconBtn(LcIcons.up, "Früher lasern", { editor.moveLayer(layer.id, true) })
                IconBtn(LcIcons.down, "Später lasern", { editor.moveLayer(layer.id, false) })
                IconBtn(LcIcons.trash, "Ebene löschen", { editor.deleteLayer(layer.id); onClose() }, tint = Lc.bad)
                Spacer(Modifier.weight(1f))
                LcButton("Fertig", onClose, kind = BtnKind.PRIMARY)
            }
        }
    }
}

@Composable
private fun Section(title: String) {
    Spacer(Modifier.height(4.dp))
    Text(title.uppercase(), style = LcTypography.labelSmall, color = Lc.faint)
}
