package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.MachineViewModel
import androidx.compose.foundation.text.KeyboardOptions

/**
 * The laser's address. Nothing is searched or switched by itself: the saved address is used, "Laser suchen"
 * lists the LumaCut Pis in the Wi-Fi to tap, or the address is typed in.
 */
@Composable
fun LaserCard(machine: MachineViewModel) {
    val host by machine.host.collectAsStateWithLifecycle()
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val disc by machine.discovery.collectAsStateWithLifecycle()
    var ip by remember(host) { mutableStateOf(host) }
    LcCard {
        CardTitle("Laser")
        Text(if (host.isBlank()) "Noch kein Laser eingestellt" else "Aktueller Laser: $host", style = LcTypography.titleMedium, color = Lc.text)
        SmallText(when {
            host.isBlank() -> "Mit „Laser suchen“ im WLAN finden oder die Adresse eintragen (steht im Router, z. B. 192.168.2.89)."
            online == true -> "Verbunden · Controller ${if (status?.connected == true) "bereit" else "nicht verbunden"}"
            online == false -> "Keine Antwort von $host – Laser einschalten und WLAN prüfen."
            else -> "Verbinde …"
        })
        Spacer(Modifier.height(12.dp))
        LcButton("Laser suchen", { machine.scanNetwork() }, icon = LcIcons.refresh, kind = BtnKind.PRIMARY, busy = disc.scanning)
        if (disc.open) {
            Spacer(Modifier.height(10.dp))
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (disc.scanning) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(Modifier.width(22.dp), strokeWidth = 2.dp, color = Lc.accent)
                    SmallText("Suche im WLAN …")
                }
                for (l in disc.found) Row(
                    Modifier.fillMaxWidth().heightIn(min = Lc.touch).clip(RoundedCornerShape(14.dp)).background(Lc.surface2)
                        .border(1.dp, Lc.line, RoundedCornerShape(14.dp)).clickable { machine.chooseLaser(l) }.padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(l.name, style = LcTypography.titleMedium, color = Lc.text, maxLines = 1)
                        SmallText("${l.host} · ${l.state}", if (l.state == "bereit") Lc.ok else Lc.warn)
                    }
                    Text("Verbinden", style = LcTypography.labelLarge, color = Lc.accent)
                }
                disc.note?.let { Banner(it, Lc.info) }
                if (!disc.scanning) TextButton(onClick = { machine.dismissDiscovery() }) { Text("Liste schließen", color = Lc.muted) }
            }
        }
        Spacer(Modifier.height(14.dp))
        OutlinedTextField(
            ip, { ip = it.filter { c -> c.isDigit() || c == '.' } }, label = { Text("Adresse eingeben") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            textStyle = LcTypography.bodyLarge.merge(NumberStyle), shape = RoundedCornerShape(14.dp),
        )
        Spacer(Modifier.height(10.dp))
        LcButton("Verbinden", { machine.connect(ip) }, enabled = ip.isNotBlank())
    }
}
