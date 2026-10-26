package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.core.Frame
import de.millione.lumacut.core.MachineStatus
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.Toolpath
import de.millione.lumacut.core.formatDuration
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private sealed interface Built {
    class Ok(val gcode: String, val toolpath: Toolpath) : Built
    class Fail(val text: String) : Built
}

/** One sentence with the next step, or null when the machine can start. */
private fun blocker(s: MachineStatus?, online: Boolean?, host: String): String? = when {
    host.isBlank() -> "Pi-Adresse fehlt – unter Einstellungen eintragen."
    online != true || s == null -> "Der Pi ist nicht erreichbar – WLAN und Pi-Adresse prüfen."
    !s.connected -> "Der Laser-Controller ist nicht verbunden – USB-Kabel am Pi prüfen."
    s.emergency_latched -> "Not-Aus ist aktiv – SKR zurücksetzen, dann unter Maschine quittieren."
    !s.ownerFree -> "Der Laser wird gerade von ${s.owner} benutzt – dort zuerst trennen."
    else -> null
}

/** Step 3: summary, optional frame, one start button, then progress from the Pi. */
@Composable
fun StartScreen(machine: MachineViewModel, editor: EditorViewModel, onMaterial: () -> Unit, onMotiv: () -> Unit) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val chosen by editor.materialKey.collectAsStateWithLifecycle()
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val host by machine.host.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    var confirm by rememberConfirm()
    var built by remember { mutableStateOf<Built?>(null) }

    // Build and check the job before it leaves the tablet. No Z values: the Pi corrects the height itself.
    LaunchedEffect(doc) {
        built = null
        built = try {
            val job = editor.buildJob(false, 7.0, 1.5)
            Built.Ok(job.gcode, withContext(Dispatchers.Default) { Toolpath.parse(job.gcode) })
        } catch (e: kotlinx.coroutines.CancellationException) { throw e
        } catch (e: Exception) { Built.Fail(e.message ?: "Der Auftrag lässt sich nicht erzeugen.") }
    }

    val job = status?.job
    val running = job?.active == true
    val framing = status?.frame?.active == true
    val ok = built as? Built.Ok
    val why = blocker(status, online, host)
    val ready = ok != null && why == null && !running && !framing
    val name = PiClient.jobNameFrom(doc.title)

    Row(Modifier.fillMaxSize().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Box(
            Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(18.dp)).background(Color(0xFF0B1015))
                .border(1.dp, Lc.line, RoundedCornerShape(18.dp)),
            contentAlignment = Alignment.Center,
        ) {
            when (val b = built) {
                null -> CircularProgressIndicator(color = Lc.accent)
                is Built.Fail -> Banner(b.text, Lc.bad, Modifier.padding(20.dp))
                is Built.Ok -> ToolpathCanvas(b.toolpath, null, status?.position, if (running) job?.line ?: 0 else 0, Modifier.fillMaxSize())
            }
        }
        Column(Modifier.width(380.dp).fillMaxHeight().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("3 · Starten", style = LcTypography.headlineSmall)
            val materialText = materialSummary(doc)
            Tile("Material", materialText ?: "noch keines gewählt", Modifier.fillMaxWidth(), if (materialText == null) Lc.warn else Lc.text)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Tile("Laserzeit (ca.)", ok?.let { formatDuration(it.toolpath.stats.seconds) } ?: "—", Modifier.weight(1f))
                Tile("Größe", ok?.toolpath?.bounds?.let { "%.0f × %.0f mm".format(it.width, it.height) } ?: "—", Modifier.weight(1f))
            }
            if (materialText == null && chosen == null) {
                Banner("Ohne Material gelten die Standardwerte der Ebenen. Besser zuerst das Material wählen.")
                LcButton("Material wählen", onMaterial, Modifier.fillMaxWidth())
            }
            (built as? Built.Fail)?.let { LcButton("Zurück zum Motiv", onMotiv, Modifier.fillMaxWidth()) }
            ok?.toolpath?.stats?.warnings?.forEach { Banner(it) }
            Spacer(Modifier.height(4.dp))

            if (running && job != null) {
                RunCard(machine, job.state, job.probe.done, job.probe.total, job.fraction, ok?.toolpath?.remainingSeconds(job.line), busy)
            } else {
                if (job?.state == "complete") Banner("Fertig – der Auftrag ist abgeschlossen, der Kopf steht geparkt.", Lc.ok)
                if (job?.state == "error" && job.error.isNotBlank()) Banner("Abgebrochen: ${job.error} – Material und Maschine prüfen, dann erneut starten.", Lc.bad)
                if (why != null) Banner(why, Lc.info)
                if (framing) {
                    Banner("Rahmen wird gefahren (Laser aus).", Lc.info)
                    LcButton("Rahmen abbrechen", { machine.action("abort") }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER, busy = "abort" in busy)
                }
                LcButton("Rahmen zeigen", { ok?.let { machine.frameAutomatic(Frame.cutPoints(it.toolpath)) } },
                    Modifier.fillMaxWidth(), LcIcons.rect, busy = "frame" in busy, enabled = ready)
                LcButton("Starten", {
                    confirm = Confirm("Auftrag starten?",
                        "Liegt das Material, und ist der Arbeitsbereich frei? Die Maschine referenziert, misst die Höhe und lasert danach von selbst.",
                        "Starten") { ok?.let { machine.startAutomatic(name, it.gcode) } }
                }, Modifier.fillMaxWidth(), LcIcons.play, BtnKind.PRIMARY, busy = "start" in busy, enabled = ready, big = true)
                SmallText("Die Maschine referenziert, tastet das Material ab, korrigiert die Höhe, lasert und parkt – alles automatisch.", Lc.faint)
            }
        }
    }
    ConfirmDialog(confirm) { confirm = null }
}

/** "Material 3 mm" of the layers that are lasered; null when none carries a material. */
private fun materialSummary(doc: de.millione.lumacut.core.Document): String? {
    val used = doc.layers.filter { l -> l.output && l.visible && doc.elements.any { it.layerId == l.id } }
    val names = used.mapNotNull { l ->
        l.materialName?.let { n -> if (l.thicknessMm > 0) "$n ${if (l.thicknessMm % 1.0 == 0.0) l.thicknessMm.toInt() else l.thicknessMm} mm" else n }
    }.distinct()
    return names.joinToString(" · ").ifEmpty { null }
}

@Composable
private fun RunCard(machine: MachineViewModel, state: String, probeDone: Int, probeTotal: Int, fraction: Double, remaining: Double?, busy: Set<String>) {
    var confirm by rememberConfirm()
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Lc.accentSoft)
            .border(1.dp, Lc.accent.copy(alpha = .3f), RoundedCornerShape(16.dp)).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(when (state) {
            "homing" -> "Maschine referenziert …"
            "probing" -> "Höhe wird gemessen …"
            else -> "Der Laser arbeitet"
        }, style = LcTypography.titleMedium)
        when (state) {
            "probing" -> {
                SmallText(if (probeTotal > 0) "Messpunkt $probeDone von $probeTotal" else "Messpunkte werden vorbereitet")
                Progress(if (probeTotal > 0) probeDone.toFloat() / probeTotal else 0f, Modifier.fillMaxWidth(), thick = true)
            }
            "running" -> {
                SmallText("${(fraction * 100).toInt()} %" + (remaining?.let { " · noch ca. ${formatDuration(it)}" } ?: ""))
                Progress(fraction.toFloat(), Modifier.fillMaxWidth(), thick = true)
            }
            else -> Progress(0f, Modifier.fillMaxWidth(), thick = true)
        }
        LcButton("Abbrechen", {
            confirm = Confirm("Auftrag abbrechen?", "Der Laser wird ausgeschaltet und der Kopf parkt.", "Abbrechen", danger = true) { machine.action("abort") }
        }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER, busy = "abort" in busy)
    }
    ConfirmDialog(confirm) { confirm = null }
}
