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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
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
    val h = headline(s, online, host)
    LcCard(accent = h.tone.color) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Eyebrow("Maschine")
                Spacer(Modifier.height(4.dp))
                Text(h.title, style = LcTypography.displaySmall, color = if (h.tone == Tone.OK || h.tone == Tone.BUSY || h.tone == Tone.OFF) Lc.text else h.tone.color)
                if (h.text.isNotBlank()) { Spacer(Modifier.height(6.dp)); Text(h.text, style = LcTypography.bodyLarge, color = Lc.muted) }
            }
            val status = s
            if (status.canControl(online)) {
                val (op, label) = when {
                    !status!!.homed -> "home" to "Referenzieren"
                    status.workpiece_surface_z == null -> "probe" to "Abtasten"
                    else -> "park" to "Parken"
                }
                LcButton(label, { machine.action(op) }, kind = BtnKind.PRIMARY, big = true, busy = op in busy)
            }
        }
        Spacer(Modifier.height(20.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            val st = s
            Tile("Referenziert", if (online == true && st != null) (if (st.homed) "Ja" else "Nein") else "—", Modifier.weight(1f),
                 if (st?.homed == true) Lc.text else Lc.warn)
            Tile("Werkstück Z", st?.workpiece_surface_z?.let { "%.2f mm".format(it) } ?: "—", Modifier.weight(1f))
            Tile("Fokus Z", st?.laser_focus_z?.let { "%.2f mm".format(it) } ?: "—", Modifier.weight(1f))
            Tile("Laserversorgung", when { st == null -> "—"; st.laser_cooling_fan_on -> st.cooldown_remaining_s?.let { "Nachlauf $it s" } ?: "Ein"; else -> "Aus" }, Modifier.weight(1f))
        }
        s?.job?.takeIf { it.active }?.let { job ->
            Spacer(Modifier.height(16.dp))
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Lc.accentSoft)
                    .border(1.dp, Lc.accent.copy(alpha = .3f), RoundedCornerShape(14.dp)).padding(14.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Column(Modifier.width(200.dp)) {
                    Text(job.file, style = LcTypography.titleMedium, maxLines = 1)
                    SmallText(if (job.state == "running") "${(job.fraction * 100).toInt()} % · Zeile ${job.line}/${job.total}" else h.title)
                }
                Progress(job.fraction.toFloat(), Modifier.weight(1f))
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
                    JogKey(LcIcons.park, "Park", enabled, center = true) { machine.action("park") }
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
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LcButton("Referenzieren", { machine.action("home") }, Modifier.weight(1f), LcIcons.home, enabled = control, busy = "home" in busy)
            LcButton("Abtasten", { machine.action("probe") }, Modifier.weight(1f), LcIcons.probe, enabled = control && homed, busy = "probe" in busy)
            LcButton("Parken", { machine.action("park") }, Modifier.weight(1f), LcIcons.park, enabled = control && homed, busy = "park" in busy)
        }
        Spacer(Modifier.height(10.dp))
        SmallText("Referenzieren: X/Y zuerst, dann Z, dann ${s?.config?.z_clearance_mm?.let { "%.0f".format(it) } ?: "20"} mm hoch. Abtasten misst die Werkstückoberfläche unter dem Laserpunkt (G30).")
    }
}

private val PAD = 88.dp

@Composable
private fun JogKey(icon: ImageVector, label: String, enabled: Boolean, center: Boolean = false, tall: Boolean = false, onClick: () -> Unit) {
    Box(
        Modifier
            .size(width = PAD, height = if (tall) PAD + PAD / 2 + 5.dp else PAD)
            .clip(RoundedCornerShape(22.dp))
            .background(if (center) Brush.verticalGradient(listOf(Lc.bg, Lc.bg)) else Brush.verticalGradient(listOf(Lc.surface3, Lc.surface2)))
            .border(1.dp, Lc.line2, RoundedCornerShape(22.dp))
            .clickable(enabled = enabled, onClickLabel = label, onClick = onClick)
            .alpha(if (enabled) 1f else .4f),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, label, tint = if (center) Lc.muted else Lc.text, modifier = Modifier.size(if (center) 24.dp else 30.dp))
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
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Lc.bg).padding(12.dp)) {
            for (l in lines) Text(l, style = LcTypography.bodySmall.copy(fontFamily = FontFamily.Monospace), color = Lc.muted, maxLines = 1)
        }
        s?.identity?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            SmallText(it.removePrefix("FIRMWARE_NAME:").substringBefore(" SOURCE_CODE_URL"), Lc.faint)
        }
    }
}
