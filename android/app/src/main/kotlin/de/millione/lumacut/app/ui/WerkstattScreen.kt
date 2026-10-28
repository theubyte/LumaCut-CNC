package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.canControl
import de.millione.lumacut.app.machine.headline

@Composable
fun WerkstattScreen(machine: MachineViewModel) {
    BoxWithConstraints(Modifier.fillMaxSize().padding(16.dp)) {
        val wide = maxWidth > 900.dp
        if (wide) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Column(Modifier.weight(1.05f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    StatusCard(machine); ExtrasCard(machine); LogCard(machine)
                }
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) { MoveCard(machine) }
            }
        } else {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                StatusCard(machine); MoveCard(machine); ExtrasCard(machine); LogCard(machine)
            }
        }
    }
}

@Composable
private fun StatusCard(machine: MachineViewModel) {
    val s by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val host by machine.host.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val readError by machine.readError.collectAsStateWithLifecycle()
    val h = headline(s, online, host, readError)
    LcCard(accent = h.tone.color) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Eyebrow("Maschine")
                Spacer(Modifier.height(4.dp))
                Text(h.title, style = if (isCompact()) LcTypography.headlineSmall else LcTypography.displaySmall,
                     color = if (h.tone == Tone.OK || h.tone == Tone.BUSY || h.tone == Tone.OFF) Lc.text else h.tone.color)
                if (h.text.isNotBlank()) { Spacer(Modifier.height(6.dp)); Text(h.text, style = LcTypography.bodyLarge, color = Lc.muted) }
            }
            val status = s
            // The next step while one is due (before: also "Parken", the third park button on this page).
            if (status.canControl(online)) {
                val next = when {
                    !status!!.homed -> "home" to "Referenzieren"
                    status.workpiece_surface_z == null -> "probe" to "Abtasten"
                    else -> null
                }
                next?.let { (op, label) -> LcButton(label, { machine.action(op) }, kind = BtnKind.PRIMARY, big = true, busy = op in busy) }
            }
        }
        Spacer(Modifier.height(20.dp))
        val st = s
        val tiles: List<@Composable (Modifier) -> Unit> = listOf(
            { m -> Tile("Referenziert", if (online == true && st != null) (if (st.homed) "Ja" else "Nein") else "—", m, if (st?.homed == true) Lc.text else Lc.warn) },
            { m -> Tile("Werkstück Z", st?.workpiece_surface_z?.let { "%.2f mm".format(it) } ?: "—", m) },
            { m -> Tile("Fokus Z", st?.laser_focus_z?.let { "%.2f mm".format(it) } ?: "—", m) },
            { m -> Tile("Laserversorgung", when { st == null -> "—"; st.laser_cooling_fan_on -> st.cooldown_remaining_s?.let { "Nachlauf $it s" } ?: "Ein"; else -> "Aus" }, m) },
        )
        // Four in a row only when the card is wide enough; else two by two (before: "Laserversorgu…" cut off).
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val perRow = if (maxWidth >= 620.dp) 4 else 2
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                for (row in tiles.chunked(perRow)) Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    for (t in row) t(Modifier.weight(1f))
                }
            }
        }
        s?.job?.takeIf { it.active }?.let { job ->
            Spacer(Modifier.height(16.dp))
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(Lc.accentSoft).padding(14.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Column(Modifier.weight(1f)) {
                    Text(job.file, style = LcTypography.titleMedium, color = Lc.text, maxLines = 1)
                    SmallText(if (job.state == "running") "${(job.fraction * 100).toInt()} % · Zeile ${job.line}/${job.total}" else h.title)
                }
                ProgressRing(job.fraction.toFloat(), "${(job.fraction * 100).toInt()} %", null, size = 72.dp)
                LcButton("Abbrechen", { machine.action("abort") }, kind = BtnKind.DANGER, busy = "abort" in busy)
            }
        }
    }
}

@Composable
private fun MoveCard(machine: MachineViewModel) {
    val s by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    var step by rememberSaveable { mutableDoubleStateOf(1.0) }
    val control = s.canControl(online)
    val homed = s?.homed == true
    LcCard {
        CardTitle("Bewegen") {
            Segmented(listOf(0.1 to "0,1", 1.0 to "1", 10.0 to "10"), step, { step = it })
            Spacer(Modifier.width(8.dp)); SmallText("mm")
        }
        if (control && !homed) Banner("Joggen erst nach dem Referenzieren.", Lc.info)
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            val enabled = control && homed
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Spacer(Modifier.size(PAD)); JogKey(LcIcons.up, "Y−", enabled) { machine.jog('Y', -step) }; Spacer(Modifier.size(PAD))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    JogKey(LcIcons.left, "X+", enabled) { machine.jog('X', step) }
                    HeadSpot(s?.position)
                    JogKey(LcIcons.right, "X−", enabled) { machine.jog('X', -step) }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Spacer(Modifier.size(PAD)); JogKey(LcIcons.down, "Y+", enabled) { machine.jog('Y', step) }; Spacer(Modifier.size(PAD))
                }
            }
            Spacer(Modifier.width(22.dp))
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                JogKey(LcIcons.up, "Z+", enabled, tall = true) { machine.jog('Z', step) }
                JogKey(LcIcons.down, "Z−", enabled, tall = true) { machine.jog('Z', -step) }
            }
        }
        Spacer(Modifier.height(20.dp))
        // Three in a row only when each gets enough room; else "Referenzieren" on its own line (before: "Referenzie…").
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val home: @Composable (Modifier) -> Unit = { m -> LcButton("Referenzieren", { machine.action("home") }, m, LcIcons.home, enabled = control, busy = "home" in busy) }
            val probe: @Composable (Modifier) -> Unit = { m -> LcButton("Abtasten", { machine.action("probe") }, m, LcIcons.probe, enabled = control && homed, busy = "probe" in busy) }
            val park: @Composable (Modifier) -> Unit = { m -> LcButton("Parken", { machine.action("park") }, m, LcIcons.park, enabled = control && homed, busy = "park" in busy) }
            if (maxWidth >= 600.dp) Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { home(Modifier.weight(1.3f)); probe(Modifier.weight(1f)); park(Modifier.weight(1f)) }
            else Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                home(Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { probe(Modifier.weight(1f)); park(Modifier.weight(1f)) }
            }
        }
        Spacer(Modifier.height(10.dp))
        SmallText("Referenzieren: X/Y zuerst, dann Z, dann ${s?.config?.z_clearance_mm?.let { "%.0f".format(it) } ?: "20"} mm hoch. Abtasten misst die Werkstückoberfläche unter dem Laserpunkt (G30).")
    }
}

/** Jog key size: smaller on the phone so the cross and the Z keys fit side by side. */
internal val PAD: androidx.compose.ui.unit.Dp @Composable get() = if (isCompact()) 66.dp else 76.dp

/** Centre of the jog cross: where the head is (work-area coordinates), not a button. */
@Composable
private fun HeadSpot(position: List<Double>?) {
    Column(
        Modifier.size(PAD).clip(RoundedCornerShape(24.dp)).background(Lc.accentSoft),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        val w = position?.takeIf { it.size >= 2 }?.let { de.millione.lumacut.core.Work.fromMachine(it[0], it[1]) }
        Text("Kopf", style = LcTypography.labelMedium, color = Lc.muted)
        Text(w?.let { "%.0f".format(it.x) } ?: "—", style = LcTypography.labelLarge.merge(NumberStyle), color = Lc.text)
        Text(w?.let { "%.0f".format(it.y) } ?: "—", style = LcTypography.labelLarge.merge(NumberStyle), color = Lc.text)
    }
}

@Composable
internal fun JogKey(icon: ImageVector, label: String, enabled: Boolean, center: Boolean = false, tall: Boolean = false, onClick: () -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    Box(
        Modifier
            .size(width = PAD, height = if (tall) PAD + PAD / 2 + 5.dp else PAD)
            .then(if (enabled && !center) Modifier.lift(shape, 5.dp) else Modifier)
            .clip(shape)
            .background(if (center) Lc.accentSoft else Lc.surface)
            .border(1.dp, if (center) Lc.accent.copy(alpha = .35f) else Lc.line, shape)
            .clickable(enabled = enabled, onClickLabel = label, onClick = onClick)
            .alpha(if (enabled) 1f else .4f),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, label, tint = if (center) Lc.accent else Lc.text, modifier = Modifier.size(if (center) 24.dp else 28.dp))
            if (center || tall) { Spacer(Modifier.height(2.dp)); Text(label, style = LcTypography.labelMedium, color = Lc.muted) }
        }
    }
}

@Composable
private fun ExtrasCard(machine: MachineViewModel) {
    val s by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val usable = online == true && s?.connected == true && s?.emergency_latched == false && s?.ownerFree == true
    LcCard {
        CardTitle("Zubehör")
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            ToggleTile(LcIcons.light, "Licht", s?.lights == true, {
                if (usable) machine.action("light", mapOf("on" to if (s?.lights == true) "0" else "1"))
            }, Modifier.weight(1f), busy = "light" in busy || !usable)
            ToggleTile(LcIcons.fan, "Abluft", s?.exhaust == true, {
                if (usable) machine.action("exhaust", mapOf("on" to if (s?.exhaust == true) "0" else "1"))
            }, Modifier.weight(1f), busy = "exhaust" in busy || !usable)
        }
        if (s?.light_dimmable != false) {
            val pi = s?.light_brightness?.let { kotlin.math.round(it).toInt() } ?: 100
            var level by remember(pi) { mutableFloatStateOf(pi.toFloat()) }
            Spacer(Modifier.height(14.dp))
            SmallText("Helligkeit ${level.toInt()} %")
            Slider(
                level, { level = it }, valueRange = 1f..100f, enabled = usable,
                onValueChangeFinished = { machine.action("light", mapOf("on" to "1", "brightness" to level.toInt().toString()), key = "light", quiet = true) },
                colors = SliderDefaults.colors(thumbColor = Lc.accent, activeTrackColor = Lc.accent, inactiveTrackColor = Lc.surface3),
            )
        }
        if (s?.emergency_latched == true) {
            Spacer(Modifier.height(14.dp))
            LcButton("Notstopp quittieren (nach SKR-Reset)", { machine.action("estop_reset") }, Modifier.fillMaxWidth(),
                     kind = BtnKind.PRIMARY, busy = "estop_reset" in busy)
        }
    }
}

@Composable
private fun LogCard(machine: MachineViewModel) {
    val s by machine.status.collectAsStateWithLifecycle()
    val lines = s?.recent.orEmpty().filterNot { it.startsWith("ok") }.takeLast(8)
    if (lines.isEmpty()) return
    LcCard {
        CardTitle("Controller-Meldungen")
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Lc.surface2).padding(12.dp)) {
            for (l in lines) Text(l, style = LcTypography.bodySmall.copy(fontFamily = FontFamily.Monospace), color = Lc.muted, maxLines = 1)
        }
        s?.identity?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            SmallText(it.removePrefix("FIRMWARE_NAME:").substringBefore(" SOURCE_CODE_URL"), Lc.faint)
        }
    }
}
