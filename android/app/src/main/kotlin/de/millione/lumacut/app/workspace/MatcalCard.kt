package de.millione.lumacut.app.workspace

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.Banner
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.CardTitle
import de.millione.lumacut.app.ui.Confirm
import de.millione.lumacut.app.ui.HowTo
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.Progress
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.core.MachineStatus
import de.millione.lumacut.core.Matcal
import de.millione.lumacut.core.materialCalibration
import java.util.Locale

/**
 * Adaptive material calibration run by the Pi: engraving field by field
 * (laser, photo, measure, next power) and cutting pass by pass on a raised
 * plate until the camera sees the hole open. The test area starts at the
 * laser point; the Pi stores the results as materials.
 */
@Composable
internal fun MatcalCard(machine: MachineViewModel, status: MachineStatus?, ready: Boolean, ask: (Confirm) -> Unit) {
    var name by rememberSaveable { mutableStateOf("") }
    var thickness by rememberSaveable { mutableStateOf("4") }
    var raised by rememberSaveable { mutableStateOf(false) }
    val supported = Matcal.FEATURE in (status?.features ?: emptyList())
    val last = status?.material_calibration
    val active = last?.state == "running" && status?.job?.state in setOf("probing", "running")
    val head = status?.position?.takeIf { it.size >= 2 }
    // fresh materials once a run has stored its results
    var seen by remember { mutableStateOf(last?.state) }
    LaunchedEffect(last?.state) {
        if (seen == "running" && last?.state == "complete") machine.refreshMaterials()
        seen = last?.state
    }
    LcCard {
        CardTitle("Automatisch mit Kamera")
        SmallText("Gravur: Der Pi lasert ein 5-mm-Feld, fotografiert es, misst Ton, Streifen und Rauchrand und rechnet daraus das " +
            "nächste – bis Dunkel, Mittel und Hell gefunden sind (meist 6–10 Felder). Schnitt: je Tempo ein Durchgang nach dem " +
            "anderen, bis die Kamera das Loch offen sieht; gespeichert wird die Einstellung mit der wenigsten Energie – " +
            "das gibt die sauberste Rückseite. Die Ergebnisse speichert der Pi als Materialien.", Lc.faint)
        if (!supported) {
            Spacer(Modifier.height(8.dp))
            Banner("Der Pi kann das noch nicht – Pi-Software aktualisieren.", Lc.info)
            return@LcCard
        }
        Spacer(Modifier.height(6.dp))
        HowTo("Kopf über eine freie, glatte Stelle der Platte fahren: der Testbereich beginnt am Laserpunkt und reicht " +
            "%.0f × %.0f mm (Gravur) bzw. %.0f × %.0f mm (Schnitt) in Richtung +X/+Y der Maschine. ".format(Matcal.ENGRAVE_W, Matcal.ENGRAVE_H, Matcal.CUT_W, Matcal.CUT_H) +
            "Zum Schneiden die Platte auf Abstandhalter legen (ca. 10 mm Luft): flach auf der Opferplatte verkohlt die Rückseite " +
            "und herausgeschnittene Teile können nicht fallen.")
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TextInput("Material", name, { name = it }, Modifier.weight(1.4f))
            NumberField("Stärke", thickness, { thickness = it }, Modifier.weight(1f), "mm")
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            SmallText("Platte")
            Segmented(listOf(false to "liegt flach", true to "hochgelegt"), raised, { raised = it })
        }
        SmallText(head?.let { "Testbereich ab X %.1f / Y %.1f (Laserpunkt jetzt)".format(Locale.GERMANY, it[0], it[1]) } ?: "Position unbekannt – erst referenzieren")
        Spacer(Modifier.height(12.dp))
        fun start(kind: String) {
            val t = thickness.replace(',', '.').toDoubleOrNull()
            if (name.isBlank() || t == null || t !in 0.1..50.0) { machine.notify("Materialname und Stärke 0,1–50 mm eintragen", true); return }
            val p = head ?: run { machine.notify("Position unbekannt – erst referenzieren", true); return }
            val what = if (kind == "engrave") "Gravur Feld für Feld (bis 18 kleine Felder, ca. 5–15 min)"
                       else "Schnitt Durchgang für Durchgang (4 Quadrate à 8 mm, ca. 10 min)"
            ask(Confirm("Materialtest starten?", "$what auf „${name.trim()}“ ab X %.0f / Y %.0f. Der Pi tastet zuerst ab und lasert dann. ".format(p[0], p[1]) +
                "Hände raus, Deckel zu, Schutzbrille auf, Abluft an – danebenbleiben.", "Lasern") {
                machine.request("matcal", quietSuccess = false) { it.materialCalibration(kind, p[0], p[1], name, t, raised) }
            })
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LcButton("Gravur kalibrieren", { start("engrave") }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, enabled = ready && head != null)
            LcButton("Schnitt kalibrieren", { start("cut") }, icon = LcIcons.laser, enabled = ready && head != null && raised)
        }
        if (!raised) SmallText("Schnitt nur mit hochgelegter Platte.", Lc.faint)
        if (last != null) {
            Spacer(Modifier.height(14.dp))
            CardTitle((if (last.kind == "engrave") "Gravur" else "Schnitt") + " · " + last.material)
            if (active) {
                Progress(if (last.kind == "engrave") last.steps / 18f else (last.steps / 20f).coerceAtMost(1f), Modifier.fillMaxWidth())
                Spacer(Modifier.height(6.dp))
                LcButton("Abbrechen", { machine.action("abort") }, kind = BtnKind.DANGER)
            }
            Matcal.lastStep(last)?.let { SmallText(it) }
            for (line in Matcal.results(last)) SmallText(line, Lc.text)
            when (last.state) {
                "complete" -> SmallText("Als Material gespeichert: " + last.saved.joinToString { "${it.name} (${it.process})" }, Lc.ok)
                "error", "aborted" -> SmallText(last.error.ifBlank { "Abgebrochen" }, Lc.bad)
            }
        }
    }
}
