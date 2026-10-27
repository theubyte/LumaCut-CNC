package de.millione.lumacut.app.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.MachineViewModel

@Composable
fun SettingsScreen(machine: MachineViewModel) {
    val host by machine.host.collectAsStateWithLifecycle()
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var confirm by rememberConfirm()
    var ip by remember { mutableStateOf(host) }

    val cfg = status?.config
    var focus by remember { mutableStateOf("") }; var clear by remember { mutableStateOf("") }; var tip by remember { mutableStateOf("") }
    var px by remember { mutableStateOf("") }; var py by remember { mutableStateOf("") }
    // whenever the Pi's values change (also by a calibration), so Speichern never writes old ones back
    LaunchedEffect(cfg?.focus_gap_mm, cfg?.z_clearance_mm, cfg?.z_switch_tip_offset_mm, cfg?.probe_offset_x_mm, cfg?.probe_offset_y_mm) {
        if (cfg != null) {
            focus = cfg.focus_gap_mm.toString(); clear = cfg.z_clearance_mm.toString(); tip = cfg.z_switch_tip_offset_mm.toString()
            px = cfg.probe_offset_x_mm?.toString() ?: ""; py = cfg.probe_offset_y_mm?.toString() ?: ""
        }
    }
    val firmware = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
        if (bytes == null) { machine.notify("Datei konnte nicht gelesen werden", true); return@rememberLauncherForActivityResult }
        confirm = Confirm("Firmware flashen?", "${bytes.size / 1024} KB\n\nDer Laser wird abgeschaltet, das SKR startet neu und muss danach neu referenziert werden. Dauer ca. 15 s. LightBurn vorher trennen.", "Flashen") {
            machine.uploadFirmware("firmware.bin", bytes)
        }
    }

    Row(Modifier.fillMaxSize().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            LaserCard(machine)
            UpdateCard(machine)
            LcCard {
                CardTitle("Arbeitsbereich")
                SmallText("360 × 340 mm, Nullpunkt oben links. Der 30-mm-Rand der Maschine ist für den Laser reserviert (Parken, Referenzieren) und wird nicht angezeigt – dort wird nie gelasert, auch kein Überlauf.")
            }
            LcCard {
                CardTitle("Über")
                SmallText("LumaCut für Android · Version ${runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: "?"}")
                status?.identity?.takeIf { it.isNotBlank() }?.let {
                    SmallText("Controller: " + it.removePrefix("FIRMWARE_NAME:").substringBefore(" SOURCE_CODE_URL"))
                }
            }
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            LcCard {
                CardTitle("Fokus & Taster")
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NumberField("Fokusabstand", focus, { focus = it }, Modifier.weight(1f), "mm")
                    NumberField("Rückzug nach Homing", clear, { clear = it }, Modifier.weight(1f), "mm")
                }
                Spacer(Modifier.height(10.dp))
                NumberField("Schalter → Laserspitze", tip, { tip = it }, Modifier.fillMaxWidth(), "mm")
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NumberField("Tasterversatz X", px, { px = it }, Modifier.weight(1f), "mm")
                    NumberField("Tasterversatz Y", py, { py = it }, Modifier.weight(1f), "mm")
                }
                Spacer(Modifier.height(14.dp))
                LcButton("Speichern", {
                    machine.saveSettings(mapOf("focus_gap_mm" to focus, "z_clearance_mm" to clear, "z_switch_tip_offset_mm" to tip,
                                               "probe_offset_x_mm" to px, "probe_offset_y_mm" to py))
                }, kind = BtnKind.PRIMARY, busy = "settings" in busy, enabled = online == true)
                Spacer(Modifier.height(10.dp))
                SmallText("Fokus Z = Werkstück Z + Fokusabstand − Schalter→Spitze. Tasterversatz = Tasterspitze relativ zum Laserpunkt. Nach Änderungen neu abtasten. " +
                    "Fokusabstand und Tasterversatz lassen sich unter Maschine → Kalibrieren einmessen.")
            }
            LcCard {
                CardTitle("Licht")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Lichteffekte", style = LcTypography.titleMedium)
                        SmallText("Blitzen beim Referenzieren, Hochdimmen beim Auftragsstart, Atmen am Ende, Blinken bei Fehlern.")
                    }
                    Switch(status?.light_effects != false, { machine.action("light", mapOf("effects" to if (it) "1" else "0"), key = "light", quiet = true) },
                           enabled = online == true && status?.light_dimmable != false)
                }
                if (status?.light_dimmable == false) {
                    Spacer(Modifier.height(8.dp))
                    SmallText("Für Dimmen und Lichteffekte die neue Firmware flashen.")
                }
            }
            LcCard {
                CardTitle("SKR-Firmware")
                val fw = status?.firmware_update
                SmallText(when {
                    fw != null && fw.state != "idle" -> "${fw.state}: ${fw.message}"
                    status?.firmware_upload_supported == true -> "Update über den Pi möglich (SD-Karte bleibt im SKR)."
                    online == true -> "Aktuelle Firmware kann keine Dateien empfangen – einmalig per SD-Karte flashen."
                    else -> "—"
                })
                Spacer(Modifier.height(10.dp))
                Progress((fw?.progress ?: 0) / 100f, Modifier.fillMaxWidth())
                Spacer(Modifier.height(14.dp))
                LcButton("firmware.bin wählen & flashen", { firmware.launch(arrayOf("application/octet-stream", "*/*")) }, icon = LcIcons.upload,
                    busy = "firmware" in busy || (fw?.state ?: "") in setOf("uploading", "rebooting"),
                    enabled = online == true && status?.firmware_upload_supported == true && status?.ownerFree == true)
            }
        }
    }
    ConfirmDialog(confirm) { confirm = null }
}
