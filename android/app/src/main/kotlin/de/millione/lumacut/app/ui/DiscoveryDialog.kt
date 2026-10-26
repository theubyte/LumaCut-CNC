package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.machine.DiscoveryState
import de.millione.lumacut.app.machine.MachineViewModel

/** "Laser auswählen": LumaCut Pis found in the Wi-Fi; a tap saves the address and connects. */
@Composable
fun DiscoveryDialog(machine: MachineViewModel, state: DiscoveryState, onManual: () -> Unit) {
    AlertDialog(
        onDismissRequest = { machine.dismissDiscovery() }, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Laser auswählen", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (state.scanning) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(Modifier.width(22.dp), strokeWidth = 2.dp, color = Lc.accent)
                    SmallText("Suche im WLAN …")
                }
                for (l in state.found) Row(
                    Modifier.fillMaxWidth().heightIn(min = Lc.touch).clip(RoundedCornerShape(14.dp)).background(Lc.surface2)
                        .border(1.dp, Lc.line, RoundedCornerShape(14.dp)).clickable { machine.chooseLaser(l) }.padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(l.name, style = LcTypography.titleMedium, maxLines = 1)
                        SmallText("${l.host} · ${l.state}", if (l.state == "bereit") Lc.ok else Lc.warn)
                    }
                    Spacer(Modifier.width(8.dp))
                    Text("Verbinden", style = LcTypography.labelLarge, color = Lc.accent)
                }
                state.note?.let { Banner(it, Lc.info) }
            }
        },
        confirmButton = { LcButton("Erneut suchen", { machine.scanNetwork() }, kind = BtnKind.PRIMARY, busy = state.scanning) },
        dismissButton = {
            Row {
                TextButton(onClick = { machine.dismissDiscovery(); onManual() }) { Text("Adresse eingeben", color = Lc.muted) }
                TextButton(onClick = { machine.dismissDiscovery() }) { Text("Schließen", color = Lc.muted) }
            }
        },
    )
}
