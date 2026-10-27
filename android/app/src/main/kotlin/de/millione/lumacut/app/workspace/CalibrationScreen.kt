package de.millione.lumacut.app.workspace

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.canControl
import de.millione.lumacut.app.ui.Banner
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.CardTitle
import de.millione.lumacut.app.ui.Confirm
import de.millione.lumacut.app.ui.ConfirmDialog
import de.millione.lumacut.app.ui.JogKey
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.PAD
import de.millione.lumacut.app.ui.Progress
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.app.ui.rememberConfirm
import de.millione.lumacut.core.CutTest
import de.millione.lumacut.core.EngraveTest
import de.millione.lumacut.core.MarlinWriter
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.MaterialTest
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Everything the machine measures about itself: head camera (lens,
 * position), camera light, probe offset, laser focus and the engraving
 * settings of a material. Each card says what is stored now and starts its
 * calibration; the automatic ones laser a small test on scrap material and
 * judge it with the head camera.
 */
@Composable
fun CalibrationScreen(machine: MachineViewModel, ws: WorkspaceViewModel = viewModel()) {
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val cal by ws.calibration.collectAsStateWithLifecycle()
    val run by ws.run.collectAsStateWithLifecycle()
    val focus by ws.focusResult.collectAsStateWithLifecycle()
    val engrave by ws.engrave.collectAsStateWithLifecycle()
    val motionResult by ws.motion.collectAsStateWithLifecycle()
    val cutSpec by ws.cut.collectAsStateWithLifecycle()
    var confirm by rememberConfirm()
    var cameraDialog by remember { mutableStateOf(false) }
    var probeDialog by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { ws.syncCalibration(machine) }

    val ready = status.canControl(online) && run == null
    val homed = status?.homed == true
    val camera = status?.camera?.available == true
    val cfg = status?.config
    val fullHd = "camera_settings" in (status?.features ?: emptyList())
    val motion = cfg?.motion?.toMotion() ?: MarlinWriter.Motion.FIRMWARE

    Row(Modifier.fillMaxSize().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            run?.let { r ->
                LcCard(padding = 16.dp, accent = Lc.accent) {
                    Text(r.title, style = LcTypography.titleMedium)
                    SmallText(r.text)
                    Spacer(Modifier.height(8.dp))
                    Progress(r.fraction, Modifier.fillMaxWidth(), thick = true)
                    Spacer(Modifier.height(10.dp))
                    LcButton("Abbrechen", { ws.cancel() }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER)
                }
            }
            if (!camera) Banner("Keine Kamera am Pi – für die Kamera-, Fokus- und Gravurtests die Kopfkamera anschließen.")

            LcCard {
                CardTitle("1 · Kopfkamera")
                SmallText(cal?.let { c ->
                    val u = c.usable(0.0)
                    "Kalibriert mit ${c.photoWidth} × ${c.photoHeight} px · Bildfeld %.0f × %.0f mm".format(u.width, u.height) +
                        (c.lens?.let { " · Genauigkeit %.2f mm".format(Locale.GERMANY, it.rmsMm) } ?: " · ohne Linsenmodell") +
                        (c.aboveSurface?.let { " · scharf %.0f mm über dem Material".format(it) } ?: "")
                } ?: "Nicht kalibriert. Grundlage für Scan und alle Kameratests: misst Linse, Maßstab und Lage zum Laser.")
                if (cal != null && fullHd && cal!!.photoWidth < 1920) {
                    Spacer(Modifier.height(8.dp))
                    Banner("Die Kamera liefert jetzt Full HD statt ${cal!!.photoWidth} × ${cal!!.photoHeight}. Neu kalibrieren: dreimal schärfere Scans und genauere Tests.", Lc.info)
                }
                Spacer(Modifier.height(12.dp))
                LcButton(if (cal == null) "Kalibrieren" else "Neu kalibrieren", { cameraDialog = true }, icon = LcIcons.camera, enabled = camera)
            }

            LcCard {
                CardTitle("2 · Kamera-Licht")
                val wb = cfg?.camera?.white_balance
                SmallText(listOf(
                    wb?.let { "Weißabgleich fest auf $it K" } ?: "Weißabgleich automatisch (Farben wechseln von Bild zu Bild)",
                    if (cal?.shading != null) "Randabfall ausgeglichen" else "Randabfall nicht gemessen",
                ).joinToString(" · "))
                Spacer(Modifier.height(6.dp))
                SmallText("Ein weißes Blatt Papier (A4) mittig auf das Bett legen. Licht auf 100 %, Weißabgleich auf neutrales Grau, " +
                    "dann fünf Bilder für den Helligkeitsabfall zum Bildrand. Dauer ca. 1 Minute, Laser bleibt aus. " +
                    "Die Gesamthelligkeit regelt die Kamera selbst nach – die gleicht der Scan in den Überlappungen aus.", Lc.faint)
                Spacer(Modifier.height(12.dp))
                LcButton("Licht kalibrieren", {
                    confirm = Confirm("Kamera-Licht kalibrieren?", "Liegt ein weißes Blatt Papier mittig auf dem Bett? Der Kopf fährt darüber, der Laser bleibt aus.", "Starten") {
                        ws.calibrateLight(machine)
                    }
                }, icon = LcIcons.light, enabled = ready && homed && camera && cal != null)
            }

            LcCard {
                CardTitle("3 · Taster-Versatz")
                val off = status?.probeOffset
                SmallText(off?.let { "Tasterspitze liegt X %+.1f / Y %+.1f mm neben dem Laserpunkt".format(Locale.GERMANY, it.x, it.y) }
                    ?: "Nicht eingetragen – ohne Versatz tastet der Pi nicht automatisch ab.")
                Spacer(Modifier.height(6.dp))
                SmallText("Der Laser graviert ein kleines Kreuz, du fährst die Tasterspitze mit den Pfeilen genau darüber, der Pi übernimmt den Versatz.", Lc.faint)
                Spacer(Modifier.height(12.dp))
                LcButton("Einmessen", { probeDialog = true }, icon = LcIcons.probe, enabled = status.canControl(online) && homed)
            }
        }

        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            LcCard {
                CardTitle("4 · Laser-Fokus")
                SmallText(cfg?.let { "Fokusabstand %.1f mm (Laser %.1f mm über dem Material)".format(Locale.GERMANY, it.focus_gap_mm, it.focus_gap_mm - it.z_switch_tip_offset_mm) } ?: "—")
                Spacer(Modifier.height(6.dp))
                SmallText("Lasert 13 kurze Linien, jede 0,5 mm höher als die vorige (−3 … +3 mm um den jetzigen Fokus). Die Kamera misst ihre Breite, " +
                    "die schmalste ist im Fokus – der Pi übernimmt den neuen Fokusabstand. Restplatte mittig, Dauer ca. 1 Minute.", Lc.faint)
                var power by remember { mutableStateOf("30") }; var speed by remember { mutableStateOf("1000") }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NumberField("Leistung", power, { power = it }, Modifier.weight(1f), "%")
                    NumberField("Tempo", speed, { speed = it }, Modifier.weight(1f), "mm/min")
                }
                Spacer(Modifier.height(12.dp))
                LcButton("Fokus-Test starten", {
                    val p = power.replace(',', '.').toDoubleOrNull(); val s = speed.replace(',', '.').toDoubleOrNull()
                    if (p == null || s == null || p !in 5.0..100.0 || s !in 100.0..motion.maxFeed) { machine.notify("Leistung 5–100 %%, Tempo 100–%.0f mm/min".format(motion.maxFeed), true); return@LcButton }
                    confirm = Confirm("Fokus-Test lasern?", "Restplatte liegt mittig? Der Laser graviert 13 Linien (ca. 1 min, Laser an – Schutzbrille). " +
                        "Danach fotografiert die Kamera sie und der Fokusabstand wird angepasst.", "Lasern") { ws.focusTest(machine, p, s) }
                }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = ready && camera && cal != null)
                focus?.let { r ->
                    Spacer(Modifier.height(12.dp))
                    FocusChart(r)
                    SmallText("Schärfste Linie bei %+.1f mm · Strahlbreite dort %.2f mm".format(Locale.GERMANY, r.bestOffset, r.widthAtBest))
                }
            }

            EngraveCard(machine, ws, engrave, ready && camera && cal != null, motion.maxFeed) { confirm = it }

            LcCard {
                CardTitle("6 · Bewegung (Tempo & Genauigkeit)")
                SmallText(if (cfg?.motion?.measured == true) "Gemessen: Beschleunigung %.0f mm/s², höchstens %.0f mm/min".format(motion.accel, motion.maxFeed)
                          else "Firmware-Werte: %.0f mm/s², höchstens %.0f mm/min (nicht gemessen)".format(motion.accel, motion.maxFeed))
                Spacer(Modifier.height(6.dp))
                SmallText("Lasert kleine Referenzmarken, fährt dann mit ausgeschaltetem Laser immer härter und schneller hin und her " +
                    "(bis 8000 mm/s² und 24000 mm/min) und lasert nach jeder Stufe eine Prüfmarke daneben. Die Kamera misst, ob sich etwas " +
                    "verschoben hat (Schrittverlust ab 0,1 mm). Gespeichert wird die letzte saubere Stufe mit Reserve – danach sind Gravuren " +
                    "schneller und der Anlauf jeder Zeile passt. Restplatte mittig, laut, Dauer 5–10 min.", Lc.faint)
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    LcButton("Bewegung kalibrieren", {
                        confirm = Confirm("Bewegungs-Kalibrierung starten?", "Restplatte liegt mittig? Der Laser graviert kleine Marken; dazwischen fährt der Kopf " +
                            "mit ausgeschaltetem Laser sehr schnell hin und her (laut). Nichts auf dem Bett, das im Weg ist. Schutzbrille, danebenbleiben.", "Starten") {
                            ws.motionCalibration(machine)
                        }
                    }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = ready && camera && cal != null)
                    if (cfg?.motion?.measured == true) LcButton("Firmware-Werte", { ws.resetMotion(machine) }, kind = BtnKind.GHOST, enabled = ready)
                }
                motionResult?.let { r ->
                    Spacer(Modifier.height(12.dp))
                    val base = r.shifts.firstOrNull()
                    base?.let { SmallText("Ohne Belastung: Prüfmarke um X %+.2f / Y %+.2f mm versetzt (Wiederholgenauigkeit, Umkehrspiel)".format(Locale.GERMANY, it.dx, it.dy)) }
                    for ((i, level) in r.levels.withIndex()) {
                        val sh = r.shifts.getOrNull(i + 1) ?: break
                        val prev = r.shifts[i]
                        val ok = i <= r.lastGood
                        SmallText("Stufe ${i + 1} · %.0f mm/s² · %.0f mm/min: ".format(level.accel, level.speed * 60) +
                            (if (!sh.found) "Marke nicht gefunden" else "Versatz X %+.2f / Y %+.2f mm".format(Locale.GERMANY, sh.dx - prev.dx, sh.dy - prev.dy)) +
                            if (ok) " · sauber" else " · Schrittverlust", if (ok) Lc.ok else Lc.bad)
                    }
                    r.kept?.let { SmallText("Gespeichert: %.0f mm/s², bis %.0f mm/min".format(it.accel, it.maxFeed), Lc.text) }
                }
            }

            CutCard(machine, ws, cutSpec, ready, motion.maxFeed) { confirm = it }
        }
    }
    if (cameraDialog) CalibrationDialog(machine, ws) { cameraDialog = false }
    if (probeDialog) ProbeOffsetDialog(machine, ws) { probeDialog = false }
    ConfirmDialog(confirm) { confirm = null }
}

/** Line width over the focus offset; the chosen focus marked. */
@Composable
private fun FocusChart(r: de.millione.lumacut.core.FocusTest.Result) {
    val seen = r.lines.filter { !it.widthMm.isNaN() }
    if (seen.isEmpty()) return
    val maxW = seen.maxOf { it.widthMm } * 1.15
    val lo = r.lines.first().offset; val hi = r.lines.last().offset
    Canvas(Modifier.fillMaxWidth().height(110.dp).background(Lc.surface2)) {
        fun x(o: Double) = ((o - lo) / (hi - lo).coerceAtLeast(0.1) * (size.width - 24) + 12).toFloat()
        fun y(wd: Double) = (size.height - 10 - wd / maxW * (size.height - 20)).toFloat()
        drawLine(Lc.accent, Offset(x(r.bestOffset), 0f), Offset(x(r.bestOffset), size.height), 2f)
        for (l in r.lines) {
            if (l.widthMm.isNaN()) drawCircle(Lc.faint, 3f, Offset(x(l.offset), size.height - 10), style = Stroke(1.5f))
            else drawCircle(Lc.text, 4f, Offset(x(l.offset), y(l.widthMm)))
        }
    }
}

@Composable
private fun EngraveCard(machine: MachineViewModel, ws: WorkspaceViewModel, outcome: WorkspaceViewModel.EngraveOutcome?, enabled: Boolean, maxFeed: Double, ask: (Confirm) -> Unit) {
    val materials by machine.materials.collectAsStateWithLifecycle()
    var name by remember { mutableStateOf("MDF") }
    var thickness by remember { mutableStateOf("3") }
    var pFrom by remember { mutableStateOf("15") }; var pTo by remember { mutableStateOf("70") }
    var sFrom by remember { mutableStateOf("1500") }; var sTo by remember { mutableStateOf("6000") }
    var interval by remember { mutableDoubleStateOf(0.1) }
    LcCard {
        CardTitle("5 · Gravur-Test (Material)")
        SmallText("Lasert 5 × 5 kleine Felder mit steigender Leistung und Geschwindigkeit. Die Kamera misst je Feld, wie dunkel und wie " +
            "gleichmäßig es wurde und ob es die Umgebung verrußt. Danach wählst du hell, mittel oder dunkel – gespeichert wird die schnellste saubere Einstellung. " +
            "Restplatte mittig, Dauer ca. 4 Minuten. Ohne Luftunterstützung danebenbleiben.", Lc.faint)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TextInput("Material", name, { name = it }, Modifier.weight(1.4f))
            NumberField("Stärke", thickness, { thickness = it }, Modifier.weight(1f), "mm")
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumberField("Leistung von", pFrom, { pFrom = it }, Modifier.weight(1f), "%")
            NumberField("bis", pTo, { pTo = it }, Modifier.weight(1f), "%")
            NumberField("Tempo von", sFrom, { sFrom = it }, Modifier.weight(1f), "mm/min")
            NumberField("bis", sTo, { sTo = it }, Modifier.weight(1f), "mm/min")
        }
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SmallText("Zeilenabstand")
            Segmented(listOf(0.08 to "0,08", 0.1 to "0,1", 0.15 to "0,15"), interval, { interval = it })
            SmallText("mm")
        }
        Spacer(Modifier.height(12.dp))
        LcButton("Gravur-Test starten", {
            fun num(t: String) = t.replace(',', '.').toDoubleOrNull()
            val a = num(pFrom); val b = num(pTo); val c = num(sFrom); val d = num(sTo)
            if (a == null || b == null || c == null || d == null || a !in 1.0..100.0 || b !in 1.0..100.0 || c !in 100.0..maxFeed || d !in 100.0..maxFeed || a >= b || c >= d) {
                machine.notify("Leistung 1–100 %%, Tempo 100–%.0f mm/min (Maschinenlimit), jeweils „von“ kleiner als „bis“".format(maxFeed), true); return@LcButton
            }
            val spec = EngraveTest.Spec(powers = MaterialTest.steps(a, b, 5), speeds = MaterialTest.steps(c, d, 5), intervalMm = interval)
            ask(Confirm("Gravur-Test lasern?", "Restplatte liegt mittig? 25 Felder à 5 × 5 mm (ca. 4 min, Laser an – Schutzbrille, danebenbleiben). " +
                "Danach fotografiert die Kamera die Felder.", "Lasern") { ws.engraveTest(machine, spec) })
        }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = enabled)

        outcome?.let { o ->
            Spacer(Modifier.height(14.dp))
            EngraveGrid(o)
            Spacer(Modifier.height(10.dp))
            for (tone in EngraveTest.Tone.entries) {
                val pick = EngraveTest.pick(o.fields, tone)
                Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(tone.label.replaceFirstChar { it.uppercase() }, style = LcTypography.titleMedium, modifier = Modifier.width(80.dp))
                    SmallText(pick?.let { "%d %% · %d mm/min · Tönung %d %%".format(it.power.roundToInt(), it.speed.roundToInt(), (it.tone * 100).roundToInt()) }
                        ?: "kein sauberes Feld", modifier = Modifier.weight(1f))
                    if (pick != null) LcButton("Speichern", {
                        val t = thickness.replace(',', '.').toDoubleOrNull() ?: 0.0
                        val label = "${name.trim().ifBlank { "Material" }} (${tone.label})"
                        val old = materials.items.firstOrNull { it.name == label && abs(it.thicknessMm - t) < 0.01 && it.process == "Gravieren" }
                        val m = Material(id = old?.id ?: java.util.UUID.randomUUID().toString(), name = label, thicknessMm = t, process = "Gravieren",
                            mode = LayerMode.FILL, powerPct = pick.power, speed = pick.speed, intervalMm = o.spec.intervalMm)
                        machine.saveMaterial(m, isNew = old == null)
                    }, kind = BtnKind.GHOST)
                }
            }
        }
    }
}

/** The measured squares as on the plate: darkness = measured tone, red frame = charred, orange = uneven or smoky. */
@Composable
private fun EngraveGrid(o: WorkspaceViewModel.EngraveOutcome) {
    val cols = o.spec.powers.size; val rows = o.spec.speeds.size
    Column {
        Row {
            Spacer(Modifier.width(64.dp))
            for (p in o.spec.powers) SmallText("${p.roundToInt()} %", modifier = Modifier.width(44.dp))
        }
        for (j in 0 until rows) Row(verticalAlignment = Alignment.CenterVertically) {
            SmallText("${o.spec.speeds[j].roundToInt()}", modifier = Modifier.width(64.dp))
            for (i in 0 until cols) {
                val f = o.fields.firstOrNull { it.power == o.spec.powers[i] && it.speed == o.spec.speeds[j] }
                Box(Modifier.padding(3.dp).size(38.dp)) {
                    Canvas(Modifier.fillMaxSize()) {
                        if (f == null) { drawRect(Lc.faint, style = Stroke(1.5f)); return@Canvas }
                        val v = (1 - f.tone).toFloat()
                        drawRect(Color(0.55f + 0.4f * v, 0.42f + 0.45f * v, 0.3f + 0.45f * v))
                        val frame = when { f.charred -> Lc.bad; !f.clean -> Lc.warn; else -> null }
                        if (frame != null) drawRect(frame, style = Stroke(4f), size = Size(size.width, size.height))
                    }
                }
            }
        }
        SmallText("Zeilen: Tempo mm/min · Spalten: Leistung · rot = verkohlt, orange = ungleichmäßig oder verrußt", Lc.faint)
    }
}

/**
 * Probe offset by hand: laser the target, jog the probe tip exactly over its
 * centre (arrows as on the Steuerung page), take over the offset.
 */
@Composable
internal fun ProbeOffsetDialog(machine: MachineViewModel, ws: WorkspaceViewModel, onClose: () -> Unit) {
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val run by ws.run.collectAsStateWithLifecycle()
    var step by remember { mutableDoubleStateOf(1.0) }
    var confirm by rememberConfirm()
    val control = status.canControl(online) && run == null && status?.homed == true
    val here = status?.position?.let { ws.probeOffsetHere(machine) }
    val saved = status?.probeOffset

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Row(Modifier.fillMaxSize().background(Lc.bg).padding(20.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            LcCard(Modifier.weight(1f)) {
                Text("Taster-Versatz einmessen", style = LcTypography.headlineSmall)
                Spacer(Modifier.height(10.dp))
                SmallText("1. Restplatte mittig auflegen. „Ziel lasern“ graviert ein Kreuz mit Kreis in die Mitte des Arbeitsbereichs " +
                    "(Pi referenziert, tastet ab, lasert, parkt). Danach fährt die Tasterspitze ungefähr darüber.\n" +
                    "2. Mit den Pfeilen die Spitze genau über die Kreuzmitte fahren – erst 1 mm, dann 0,1 mm. Mit Z− näher heran, dann sieht man es besser.\n" +
                    "3. „Übernehmen“ speichert den Versatz auf dem Pi. Danach neu abtasten.")
                Spacer(Modifier.height(14.dp))
                run?.let { r -> SmallText(r.text, Lc.accent); Spacer(Modifier.height(6.dp)); Progress(r.fraction, Modifier.fillMaxWidth()); Spacer(Modifier.height(10.dp)) }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    LcButton("Ziel lasern", {
                        confirm = Confirm("Tasterziel lasern?", "Restplatte liegt mittig? Kurzer Laserlauf (Kreuz 10 mm, ca. 1 min inkl. Abtasten).", "Lasern") { ws.laserProbeTarget(machine) }
                    }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = control)
                    LcButton("Taster zum Ziel", { ws.tipOverTarget(machine) }, icon = LcIcons.probe, enabled = control, busy = "moveto" in busy)
                    if (run != null) LcButton("Abbrechen", { ws.cancel() }, kind = BtnKind.DANGER)
                }
                Spacer(Modifier.height(18.dp))
                SmallText(buildString {
                    append("Gespeichert: ")
                    append(saved?.let { "X %+.2f  Y %+.2f mm".format(Locale.GERMANY, it.x, it.y) } ?: "—")
                    append("\nTaster jetzt über dem Ziel → ")
                    append(here?.let { "X %+.2f  Y %+.2f mm".format(Locale.GERMANY, it.x, it.y) } ?: "—")
                    if (here != null && saved != null) append("  (Änderung %.2f mm)".format(Locale.GERMANY, here.dist(saved)))
                }, Lc.text)
                Spacer(Modifier.height(14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    LcButton("Übernehmen", {
                        confirm = Confirm("Versatz übernehmen?", here?.let { "Tasterspitze X %+.2f / Y %+.2f mm neben dem Laserpunkt.\n\nDie gemessene Oberfläche wird dabei verworfen.".format(Locale.GERMANY, it.x, it.y) } ?: "", "Übernehmen") {
                            ws.saveProbeOffset(machine)
                        }
                    }, kind = BtnKind.PRIMARY, enabled = control && here != null, busy = "settings" in busy)
                    LcButton("Schließen", onClose, kind = BtnKind.GHOST)
                }
            }
            LcCard(Modifier.width(420.dp)) {
                CardTitle("Bewegen") {
                    Segmented(listOf(0.1 to "0,1", 1.0 to "1", 10.0 to "10"), step, { step = it })
                    Spacer(Modifier.width(8.dp)); SmallText("mm")
                }
                Spacer(Modifier.height(14.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Spacer(Modifier.size(PAD)); JogKey(LcIcons.up, "Y−", control) { machine.jog('Y', -step) }; Spacer(Modifier.size(PAD))
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            JogKey(LcIcons.left, "X+", control) { machine.jog('X', step) }
                            Spacer(Modifier.size(PAD))
                            JogKey(LcIcons.right, "X−", control) { machine.jog('X', -step) }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Spacer(Modifier.size(PAD)); JogKey(LcIcons.down, "Y+", control) { machine.jog('Y', step) }; Spacer(Modifier.size(PAD))
                        }
                    }
                    Spacer(Modifier.width(18.dp))
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        JogKey(LcIcons.up, "Z+", control, tall = true) { machine.jog('Z', step) }
                        JogKey(LcIcons.down, "Z−", control, tall = true) { machine.jog('Z', -step) }
                    }
                }
                Spacer(Modifier.height(12.dp))
                SmallText(status?.position?.let { "Kopf X %.2f · Y %.2f · Z %.2f".format(Locale.GERMANY, it.getOrElse(0) { 0.0 }, it.getOrElse(1) { 0.0 }, it.getOrElse(2) { 0.0 }) } ?: "—")
                SmallText("Z geht nicht tiefer als 2 mm über die gemessene Oberfläche (Schutz durch den Pi).", Lc.faint)
            }
        }
    }
    ConfirmDialog(confirm) { confirm = null }
}

/**
 * Guided cut test: lasered squares (rows = passes, columns = speed); the
 * operator taps the ones that fell out, the app keeps the quickest with
 * reserve as the cutting setting of the material.
 */
@Composable
private fun CutCard(machine: MachineViewModel, ws: WorkspaceViewModel, spec: CutTest.Spec?, ready: Boolean, maxFeed: Double, ask: (Confirm) -> Unit) {
    val materials by machine.materials.collectAsStateWithLifecycle()
    var name by remember { mutableStateOf("MDF") }
    var thickness by remember { mutableStateOf("3") }
    var power by remember { mutableStateOf("100") }
    var sFrom by remember { mutableStateOf("150") }; var sTo by remember { mutableStateOf("600") }
    var maxPasses by remember { mutableStateOf(3) }
    var through by remember(spec) { mutableStateOf(emptySet<Pair<Int, Int>>()) }
    LcCard {
        CardTitle("7 · Schnitt-Test (geführt)")
        SmallText("1. Restplatte des Materials mittig auflegen, Stärke eintragen. 2. Der Laser schneidet 5 × $maxPasses Quadrate (8 mm): " +
            "nach rechts schneller, nach unten mehr Durchgänge; ein kleiner Pfeil oben links zeigt die Lage. 3. Platte umdrehen, Quadrate " +
            "vorsichtig herausdrücken. 4. Hier antippen, welche herausgefallen sind – die App nimmt die schnellste sichere Einstellung. " +
            "Ohne Luftunterstützung kann MDF beim Schneiden aufflammen: danebenbleiben.", Lc.faint)
        if (spec == null) {
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TextInput("Material", name, { name = it }, Modifier.weight(1.4f))
                NumberField("Stärke", thickness, { thickness = it }, Modifier.weight(1f), "mm")
                NumberField("Leistung", power, { power = it }, Modifier.weight(1f), "%")
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                NumberField("Tempo von", sFrom, { sFrom = it }, Modifier.weight(1f), "mm/min")
                NumberField("bis", sTo, { sTo = it }, Modifier.weight(1f), "mm/min")
                SmallText("Durchgänge")
                Segmented(listOf(1 to "1", 2 to "2", 3 to "3", 4 to "4"), maxPasses, { maxPasses = it })
            }
            Spacer(Modifier.height(12.dp))
            LcButton("Schnitt-Test lasern", {
                fun num(t: String) = t.replace(',', '.').toDoubleOrNull()
                val t = num(thickness); val pw = num(power); val a = num(sFrom); val b = num(sTo)
                if (t == null || pw == null || a == null || b == null || t !in 0.1..20.0 || pw !in 10.0..100.0 || a !in 30.0..maxFeed || b !in 30.0..maxFeed || a >= b) {
                    machine.notify("Stärke 0,1–20 mm, Leistung 10–100 %%, Tempo 30–%.0f mm/min, „von“ kleiner als „bis“".format(maxFeed), true); return@LcButton
                }
                val s = CutTest.Spec(powerPct = pw, speeds = MaterialTest.steps(a, b, 5), passes = (1..maxPasses).toList(), thicknessMm = t)
                ask(Confirm("Schnitt-Test lasern?", "Restplatte (%s mm) liegt mittig? Der Laser schneidet ${5 * maxPasses} Quadrate (Laser an, kann einige Minuten dauern). ".format(thickness) +
                    "Abluft an, Schutzbrille, danebenbleiben.", "Lasern") { ws.cutTest(machine, s) })
            }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = ready)
        } else {
            Spacer(Modifier.height(12.dp))
            Text("Welche Quadrate sind herausgefallen?", style = LcTypography.titleMedium)
            SmallText("Antippen = durch (grün). Lage wie auf der Platte, Pfeil oben links.", Lc.faint)
            Spacer(Modifier.height(8.dp))
            Row { Spacer(Modifier.width(64.dp)); for (sp in spec.speeds) SmallText("${sp.roundToInt()}", modifier = Modifier.width(52.dp)) }
            for ((j, p) in spec.passes.withIndex()) Row(verticalAlignment = Alignment.CenterVertically) {
                SmallText("${p}×", modifier = Modifier.width(64.dp))
                for (i in spec.speeds.indices) {
                    val on = (i to j) in through
                    Box(Modifier.padding(3.dp).size(46.dp).background(if (on) Lc.ok.copy(alpha = .35f) else Lc.surface2)
                        .clickable { through = if (on) through - (i to j) else through + (i to j) }, contentAlignment = Alignment.Center) {
                        if (on) Icon(LcIcons.check, null, tint = Lc.ok)
                    }
                }
            }
            SmallText("Spalten: Tempo mm/min · Zeilen: Durchgänge · Leistung %.0f %%".format(spec.powerPct), Lc.faint)
            Spacer(Modifier.height(10.dp))
            val pick = CutTest.pick(spec, through)
            if (pick == null) SmallText("Noch nichts angetippt." + if (through.isEmpty()) " Ist keines durch: Leistung erhöhen oder mehr Durchgänge." else "")
            else {
                SmallText("Empfehlung: %.0f %% · %.0f mm/min · %d× (Fokus je Durchgang %.1f mm tiefer)".format(Locale.GERMANY, pick.powerPct, pick.speed, pick.passes, pick.zStep), Lc.text)
                if (!pick.reserve) SmallText("Ohne Reserve: kein langsameres Quadrat war ebenfalls durch – lieber eine Stufe langsamer testen.", Lc.warn)
                if (pick.inconsistent) SmallText("Auffällig: ein langsameres Quadrat mit gleichen Durchgängen ist nicht durch – Markierung prüfen.", Lc.warn)
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                LcButton("Als Material speichern", {
                    val p = pick ?: return@LcButton
                    val label = name.trim().ifBlank { "Material" }
                    val old = materials.items.firstOrNull { it.name == label && abs(it.thicknessMm - spec.thicknessMm) < 0.01 && it.process == "Schneiden" }
                    machine.saveMaterial(Material(id = old?.id ?: java.util.UUID.randomUUID().toString(), name = label, thicknessMm = spec.thicknessMm, process = "Schneiden",
                        mode = LayerMode.LINE, powerPct = p.powerPct, speed = p.speed, passes = p.passes, zStepMm = p.zStep), isNew = old == null)
                }, kind = BtnKind.PRIMARY, enabled = pick != null)
                LcButton("Neuer Test", { ws.clearCut() }, kind = BtnKind.GHOST)
            }
        }
    }
}
