package de.millione.lumacut.app.workspace

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.CardTitle
import de.millione.lumacut.app.ui.Confirm
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.SmallText
import java.util.Locale
import kotlin.math.roundToInt

/** 8 · Ringing: how much the axes swing after sharp corners, and at which frequency. */
@Composable
internal fun RingingCard(machine: MachineViewModel, ws: WorkspaceViewModel, enabled: Boolean, ask: (Confirm) -> Unit) {
    val result by ws.ringing.collectAsStateWithLifecycle()
    LcCard {
        CardTitle("8 · Schwing-Test (Nachschwingen)")
        SmallText("Lasert je Achse kurze Haken: quer, scharfe Ecke, dann 30 mm gerade – bei mehreren Geschwindigkeiten. Schwingt eine Achse nach der Ecke " +
            "nach, wellt sich die gerade Linie. Die Kamera misst wie stark und wie schnell (Hz). Restplatte mittig, ca. 2 min.", Lc.faint)
        Spacer(Modifier.height(12.dp))
        LcButton("Schwing-Test starten", {
            ask(Confirm("Schwing-Test lasern?", "Restplatte liegt mittig? Kurze Linien bei bis zu 6000 mm/min (Laser an – Schutzbrille, danebenbleiben).", "Lasern") { ws.ringingTest(machine) })
        }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = enabled)
        result?.let { list ->
            Spacer(Modifier.height(12.dp))
            for (r in list) {
                val tone = when { !r.found -> Lc.faint; !r.rings -> Lc.ok; r.amplitude < 0.15 -> Lc.warn; else -> Lc.bad }
                SmallText("%c-Achse schwingt · Linie in %c bei %.0f mm/min: ".format(r.swingingAxis, r.leg.axis, r.leg.speed) + when {
                    !r.found -> "nicht erkannt"
                    !r.rings -> "ruhig (%.2f mm)".format(Locale.GERMANY, r.amplitude)
                    else -> "%.2f mm%s".format(Locale.GERMANY, r.amplitude, if (r.frequency.isNaN()) "" else " · %.0f Hz".format(r.frequency))
                }, tone)
            }
            if (list.any { it.rings }) SmallText("Abhilfe: Riemen der schwingenden Achse spannen, Laufrollen ohne Spiel, Kopf fest; " +
                "sonst Beschleunigung senken. Die Frequenz ist der Wert für Input Shaping in der Firmware.", Lc.faint)
        }
    }
}

/** 11 · Backlash: play when the direction reverses. */
@Composable
internal fun BacklashCard(machine: MachineViewModel, ws: WorkspaceViewModel, enabled: Boolean, ask: (Confirm) -> Unit) {
    val result by ws.backlash.collectAsStateWithLifecycle()
    LcCard {
        CardTitle("11 · Umkehrspiel")
        SmallText("Lasert Linienpaare 1 mm auseinander, die erste von links bzw. oben angefahren, die zweite von der anderen Seite. " +
            "Spiel in Riemen oder Zahnrädern verschiebt die zweite – die Kamera misst um wie viel. Restplatte mittig, ca. 1 min.", Lc.faint)
        Spacer(Modifier.height(12.dp))
        LcButton("Umkehrspiel messen", {
            ask(Confirm("Umkehrspiel-Test lasern?", "Restplatte liegt mittig? 12 kurze Linien (Laser an – Schutzbrille).", "Lasern") { ws.backlashTest(machine) })
        }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = enabled)
        result?.let { r ->
            Spacer(Modifier.height(10.dp))
            for (a in listOf('X', 'Y')) {
                val v = r[a] ?: Double.NaN
                SmallText("$a: " + if (v.isNaN()) "nicht gemessen" else "%.2f mm".format(Locale.GERMANY, v),
                    when { v.isNaN() -> Lc.faint; v <= 0.05 -> Lc.ok; v <= 0.1 -> Lc.warn; else -> Lc.bad })
            }
            SmallText("Bis 0,05 mm sehr gut, bis 0,1 mm in Ordnung. Darüber: Riemen nachspannen, Madenschrauben der Zahnräder und Exzenter der Laufrollen prüfen.", Lc.faint)
        }
    }
}

/** 10 · Grey-scale curve for photo engraving. */
@Composable
internal fun ToneCard(machine: MachineViewModel, ws: WorkspaceViewModel, editor: EditorViewModel, enabled: Boolean, maxFeed: Double, ask: (Confirm) -> Unit) {
    val result by ws.tone.collectAsStateWithLifecycle()
    var power by remember { mutableStateOf("40") }; var speed by remember { mutableStateOf("3000") }
    LcCard {
        CardTitle("10 · Graustufen (Fotos)")
        SmallText("10 Felder mit gleicher Geschwindigkeit und steigender Leistung. Die Kamera misst, wie dunkel jedes wird – daraus wird eine Kurve, " +
            "damit Fotos die Grautöne des Originals bekommen statt zu dunkel zu werden. Leistung und Tempo wie für Fotos auf diesem Material.", Lc.faint)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumberField("Höchste Leistung", power, { power = it }, Modifier.weight(1f), "%")
            NumberField("Tempo", speed, { speed = it }, Modifier.weight(1f), "mm/min")
        }
        Spacer(Modifier.height(12.dp))
        LcButton("Graustufen-Test starten", {
            val p = power.replace(',', '.').toDoubleOrNull(); val s = speed.replace(',', '.').toDoubleOrNull()
            if (p == null || s == null || p !in 5.0..100.0 || s !in 300.0..maxFeed) { machine.notify("Leistung 5–100 %%, Tempo 300–%.0f mm/min".format(maxFeed), true); return@LcButton }
            ask(Confirm("Graustufen-Test lasern?", "Restplatte des Foto-Materials liegt mittig? 10 Felder à 5 × 5 mm (Laser an – Schutzbrille).", "Lasern") { ws.toneTest(machine, p, s) })
        }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = enabled)
        result?.let { o ->
            Spacer(Modifier.height(12.dp))
            Canvas(Modifier.fillMaxWidth().height(90.dp).background(Lc.surface2)) {
                val path = Path()
                o.curve.forEachIndexed { k, v ->
                    val x = k / 10f * size.width; val y = size.height - v.toFloat() * size.height
                    if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawLine(Lc.faint, Offset(0f, size.height), Offset(size.width, 0f), 1.5f)
                drawPath(path, Lc.accent, style = Stroke(3f))
            }
            SmallText("Waagrecht: gewünschte Dunkelheit · senkrecht: nötige Leistung · Diagonale = ohne Kurve.", Lc.faint)
            SmallText("Gemessen: " + o.tones.joinToString(" · ") { "${(it * 100).roundToInt()} %" })
            Spacer(Modifier.height(8.dp))
            LcButton("Auf Ebene „Gravieren“ übernehmen", { editor.applyToneCurve(o.curve, o.spec.maxPower, o.spec.speed) }, kind = BtnKind.GHOST)
        }
    }
}

/** 9 · Height without touching: work-laser glimmer spot now, red line laser later. */
@Composable
internal fun Height3DCard(machine: MachineViewModel, ws: WorkspaceViewModel, ready: Boolean, ask: (Confirm) -> Unit) {
    val status by machine.status.collectAsStateWithLifecycle()
    val cal by ws.calibration.collectAsStateWithLifecycle()
    val power by ws.spotPower.collectAsStateWithLifecycle()
    val test by ws.spotTest.collectAsStateWithLifecycle()
    val gpio = status?.line_laser?.gpio
    var pin by remember(gpio) { mutableStateOf(gpio?.toString() ?: "") }
    LcCard {
        CardTitle("9 · 3D-Höhe ohne Berühren")
        SmallText("Ein Licht am Kopf fällt aufs Material, die Kamera sieht es schräg – je höher die Oberfläche, desto weiter wandert es im Bild. " +
            "So misst die Maschine Höhen, ohne den Taster aufzusetzen (an den angetippten Abtastpunkten oder als 3D-Karte).", Lc.faint)

        Spacer(Modifier.height(12.dp))
        Text("Mit dem Laserpunkt (jetzt)", style = LcTypography.titleMedium)
        SmallText(listOf(
            power?.let { "Leistung S$it (%.1f %%)".format(Locale.GERMANY, it / 2.55) } ?: "Leistung noch nicht getestet",
            if (cal?.spot != null) "kalibriert" else "nicht kalibriert",
        ).joinToString(" · "))
        SmallText("1. Leistungstest: kurze Linien mit 0,4–5 %; die Kamera prüft, ab wann sie den Punkt sieht und ab wann eine Spur bleibt. " +
            "2. Kalibrieren an der flachen Platte in 6 Höhen. 3. Messen unter Maschine → Arbeitsplatz scannen → Abtasten.", Lc.faint)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LcButton("1 · Leistung testen", {
                ask(Confirm("Laserpunkt-Leistungstest?", "Restplatte liegt mittig? 13 kurze Linien mit sehr wenig Leistung (Laser an – Schutzbrille). " +
                    "Ein Material, auf dem der Punkt Spuren hinterlässt, ist ungeeignet.", "Lasern") { ws.spotPowerTest(machine) })
            }, icon = LcIcons.laser, enabled = ready && cal != null)
            LcButton("2 · Kalibrieren", {
                ask(Confirm("Laserpunkt kalibrieren?", "Flache Restplatte mittig? 6 kurze Linien mit S$power in verschiedenen Höhen.", "Starten") { ws.spotCalibrate(machine) })
            }, icon = LcIcons.camera, enabled = ready && cal != null && power != null)
        }
        test?.let { steps ->
            Spacer(Modifier.height(8.dp))
            SmallText(steps.joinToString("  ") { s -> "S${s.s}:" + (if (s.seen) "✓" else "–") + (if (!s.mark.isNaN() && s.mark >= 0.05) "✗" else "") },
                Lc.muted)
            SmallText("✓ = Punkt gesehen · ✗ = Spur hinterlassen", Lc.faint)
        }

        Spacer(Modifier.height(16.dp))
        Text("Mit dem roten Linienlaser (wenn eingebaut)", style = LcTypography.titleMedium)
        SmallText(when {
            gpio == null -> "Nicht eingerichtet – roter 650-nm-Linienlaser (5 mW, 5 V) am Kopf, geschaltet über einen Pi-GPIO."
            cal?.line == null -> "An GPIO $gpio · noch nicht kalibriert"
            else -> "An GPIO $gpio · kalibriert – 3D-Scan unter Arbeitsplatz scannen → Abtasten"
        })
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumberField("GPIO (BCM)", pin, { pin = it }, Modifier.width(150.dp))
            LcButton("Speichern", {
                val n = pin.trim().toIntOrNull()
                if (pin.isNotBlank() && (n == null || n !in 2..27)) { machine.notify("GPIO 2–27 oder leer", true); return@LcButton }
                ws.setLineLaserGpio(machine, n)
            }, kind = BtnKind.GHOST, enabled = status != null)
            LcButton("Kalibrieren", {
                ask(Confirm("Linienlaser kalibrieren?", "Flache Restplatte mittig? Der Kopf fährt in 6 Höhen, der Linienlaser blinkt jeweils kurz (kein Brennen).", "Starten") { ws.lineCalibrate(machine) })
            }, icon = LcIcons.camera, enabled = ready && gpio != null && cal != null)
        }
    }
}
