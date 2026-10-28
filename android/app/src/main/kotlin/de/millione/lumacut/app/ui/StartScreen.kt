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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
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
    !s.coordOk -> "Der Pi-Dienst kennt die neue Achsenrichtung noch nicht – Pi-Dienst aktualisieren."
    "autorun_mesh" !in s.features -> "Der Pi kennt den automatischen Ablauf noch nicht – Pi-Dienst aktualisieren."
    else -> null
}

/** Step 3: which plate, summary, optional frame, one start button, then progress from the Pi. */
@Composable
fun StartScreen(machine: MachineViewModel, editor: EditorViewModel, onMaterial: () -> Unit, onMotiv: () -> Unit) {
    val project by editor.project.collectAsStateWithLifecycle()
    val chosen by editor.materialKey.collectAsStateWithLifecycle()
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val host by machine.host.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val update by machine.update.collectAsStateWithLifecycle()
    var confirm by rememberConfirm()
    var built by remember { mutableStateOf<Built?>(null) }
    // Plate to laser: the one being edited, unless the operator picks another here.
    var chosenPlate by rememberSaveable { mutableIntStateOf(project.activePlate) }
    val plate = chosenPlate.coerceIn(0, project.plateCount - 1)
    val doc = project.plateView(plate)
    val multi = project.plateCount > 1
    // Plates lasered in this session (check mark), and the one the last start was for.
    var done by remember { mutableStateOf(emptySet<Int>()) }
    var startedPlate by rememberSaveable { mutableStateOf<Int?>(null) }

    // Build and check the job before it leaves the tablet. No Z values: the Pi corrects the height itself.
    LaunchedEffect(project, plate) {
        built = null
        if (doc.elements.isEmpty()) { built = Built.Fail(if (multi) "Platte ${plate + 1} ist leer – eine andere Platte wählen." else "Noch kein Motiv – zuerst etwas gestalten."); return@LaunchedEffect }
        built = try {
            val job = editor.buildJob(false, 7.0, 1.5, plate)
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
    val name = PiClient.jobNameFrom(if (multi) "${project.title} Platte ${plate + 1}" else project.title)
    LaunchedEffect(job?.state, startedPlate) {
        val p = startedPlate
        if (job?.state == "complete" && p != null) done = done + p
    }
    val next = (plate + 1 until project.plateCount).firstOrNull { project.plateSize(it) > 0 && it !in done }

    val compact = isCompact()
    Column(Modifier.fillMaxSize()) {
    // On the phone the heading stands above the preview; on the tablet it heads the right column.
    if (compact) ScreenTitle("Starten", "Prüfen, Rahmen zeigen, lasern.", step = 3, modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp))
    SplitPane(Modifier.padding(16.dp), sideWidth = 400.dp, mainShare = .4f, main = { mod ->
        CanvasSurface(mod) {
            when (val b = built) {
                null -> CircularProgressIndicator(color = Lc.accent, modifier = Modifier.align(Alignment.Center))
                is Built.Fail -> Banner(b.text, Lc.bad, Modifier.align(Alignment.Center).padding(20.dp))
                is Built.Ok -> ToolpathCanvas(b.toolpath, null, status?.position, if (running) job?.line ?: 0 else 0, Modifier.fillMaxSize())
            }
        }
    }, side = { mod ->
        Column(mod.verticalScroll(rememberScrollState()).padding(bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (!compact) ScreenTitle("Starten", "Prüfen, Rahmen zeigen, lasern.", step = 3)
            if (multi) {
                SmallText("Welche Platte soll gelasert werden?")
                PlateChips(project, plate, { if (!running) chosenPlate = it }, Modifier.fillMaxWidth(), done)
            }
            if (update.available && !running) Banner("Update ${update.info?.version_name} verfügbar – unter Einstellungen aktualisieren.", Lc.info)
            val materialText = materialSummary(doc)
            LcCard(Modifier.fillMaxWidth(), padding = 16.dp) {
                Tile("Material", materialText ?: "noch keines gewählt", Modifier.fillMaxWidth(), if (materialText == null) Lc.warn else Lc.text)
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Tile("Laserzeit (ca.)", ok?.let { formatDuration(it.toolpath.stats.seconds) } ?: "—", Modifier.weight(1f))
                    Tile("Größe", ok?.toolpath?.bounds?.let { "%.0f × %.0f mm".format(it.width, it.height) } ?: "—", Modifier.weight(1f))
                }
            }
            if (materialText == null && chosen == null) {
                Banner("Ohne Material gelten die Standardwerte der Ebenen. Besser zuerst das Material wählen.")
                LcButton("Material wählen", onMaterial, Modifier.fillMaxWidth(), LcIcons.material)
            }
            (built as? Built.Fail)?.let { LcButton("Zurück zum Motiv", onMotiv, Modifier.fillMaxWidth(), LcIcons.editor) }
            ok?.toolpath?.stats?.warnings?.forEach { Banner(it) }

            if (running && job != null) {
                RunCard(machine, job.step, job.lastPaths, job.probe.done, job.probe.total, job.fraction, ok?.toolpath?.remainingSeconds(job.line), busy)
            } else {
                if (job?.state == "aborted") Banner("Abgebrochen – der Laser ist aus. Zum Wiederholen erneut Starten.", Lc.info)
                if (job?.state == "complete") {
                    val which = startedPlate?.takeIf { multi }?.let { "Platte ${it + 1} " } ?: ""
                    Banner("Fertig – ${which}ist gelasert, der Kopf steht geparkt.", Lc.ok)
                    if (multi && next != null && startedPlate == plate)
                        LcButton("Weiter mit Platte ${next + 1}", { chosenPlate = next }, Modifier.fillMaxWidth(), LcIcons.right)
                }
                if (job?.state == "error" && job.error.isNotBlank()) Banner(job.error, Lc.bad)
                if (why != null) Banner(why, Lc.info)
                if (framing) {
                    Banner("Rahmen wird gefahren (Laser aus).", Lc.info)
                    LcButton("Rahmen abbrechen", { machine.action("abort") }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER, busy = "abort" in busy)
                }
                LcButton("Rahmen zeigen", { ok?.let { machine.frameAutomatic(Frame.cutPoints(it.toolpath)) } },
                    Modifier.fillMaxWidth(), LcIcons.rect, busy = "frame" in busy, enabled = ready)
                LcButton("Starten", {
                    confirm = Confirm("Auftrag starten?",
                        (if (multi) "Liegt Platte ${plate + 1} in der Maschine? " else "Liegt das Material? ") +
                            "Ist der Arbeitsbereich frei? Die Maschine referenziert, misst die Höhe und lasert danach von selbst.",
                        "Starten") { ok?.let { startedPlate = plate; machine.startAutomatic(name, it.gcode) } }
                }, Modifier.fillMaxWidth(), LcIcons.play, BtnKind.PRIMARY, busy = "start" in busy, enabled = ready, big = true)
                StepList(listOf("Referenzieren", "Material abtasten", "Höhe korrigieren", "Lasern", "Parken"))
            }
        }
    })
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
private fun RunCard(machine: MachineViewModel, state: String, lastPaths: Boolean, probeDone: Int, probeTotal: Int, fraction: Double, remaining: Double?, busy: Set<String>) {
    var confirm by rememberConfirm()
    Column(
        Modifier.fillMaxWidth().lift(RoundedCornerShape(24.dp)).clip(RoundedCornerShape(24.dp)).background(Lc.surface)
            .border(2.dp, Lc.accent.copy(alpha = .5f), RoundedCornerShape(24.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(when (state) {
            "homing" -> "Maschine referenziert …"
            "probing" -> "Höhe wird gemessen …"
            "focusing" -> "Höhenkorrektur wird berechnet …"
            "finishing", "parking" -> "Letzte Bahnen, dann Parken"
            else -> if (lastPaths) "Letzte Bahnen, dann Parken" else "Der Laser arbeitet"
        }, style = LcTypography.titleLarge, color = Lc.text)
        when (state) {
            "probing" -> {
                SmallText(if (probeTotal > 0) "Messpunkt $probeDone von $probeTotal" else "Messpunkte werden vorbereitet")
                Progress(if (probeTotal > 0) probeDone.toFloat() / probeTotal else 0f, Modifier.fillMaxWidth(), thick = true)
            }
            "running", "finishing" -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                ProgressRing(fraction.toFloat(), "${(fraction * 100).toInt()} %", "gelasert", size = 120.dp)
                Column(Modifier.weight(1f)) {
                    Text(remaining?.let { "noch ca. ${formatDuration(it)}" } ?: "Restzeit wird berechnet", style = LcTypography.titleMedium, color = Lc.text)
                    SmallText("Das Display bleibt an, solange der Laser arbeitet.")
                }
            }
            else -> Progress(0f, Modifier.fillMaxWidth(), thick = true)
        }
        LcButton("Abbrechen", {
            confirm = Confirm("Auftrag abbrechen?", "Der Laser wird ausgeschaltet und der Kopf parkt.", "Abbrechen", danger = true) { machine.action("abort") }
        }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER, busy = "abort" in busy)
    }
    ConfirmDialog(confirm) { confirm = null }
}

/** What the automatic run does, as numbered steps, so a beginner knows what to expect. */
@Composable
private fun StepList(steps: List<String>) {
    Column(Modifier.fillMaxWidth().padding(top = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        SmallText("Nach dem Start läuft alles von selbst:", Lc.muted)
        for ((i, step) in steps.withIndex()) Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(22.dp).clip(androidx.compose.foundation.shape.CircleShape).background(Lc.surface3), contentAlignment = Alignment.Center) {
                Text("${i + 1}", style = LcTypography.labelMedium, color = Lc.muted)
            }
            Spacer(Modifier.width(10.dp))
            Text(step, style = LcTypography.bodyMedium, color = Lc.text)
        }
    }
}
