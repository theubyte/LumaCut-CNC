package de.millione.lumacut.app.workspace

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.canControl
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.Progress
import de.millione.lumacut.app.ui.SmallText

/**
 * "Scannen" with a choice of what: the marked areas, only under the motif,
 * or the whole work area. [anchor] draws the button and gets the function
 * that opens the menu; [onSetup] leads to marking areas / calibrating.
 */
@Composable
fun ScanMenu(machine: MachineViewModel, editor: EditorViewModel, ws: WorkspaceViewModel, onSetup: (() -> Unit)? = null,
             anchor: @Composable (open: () -> Unit) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val cal by ws.calibration.collectAsStateWithLifecycle()
    val areas by ws.areas.collectAsStateWithLifecycle()
    val run by ws.run.collectAsStateWithLifecycle()
    val doc by editor.doc.collectAsStateWithLifecycle()
    val ready = status.canControl(online) && run == null && status?.homed == true && status?.camera?.available == true && cal != null
    val why = when {
        status?.camera?.available != true -> "Keine Kamera am Pi"
        cal == null -> "Kopfkamera erst kalibrieren"
        status?.homed != true -> "Erst referenzieren"
        run != null -> "Läuft gerade: ${run?.title}"
        !status.canControl(online) -> "Pi nicht bereit"
        else -> null
    }
    Box {
        anchor { open = true }
        DropdownMenu(open, { open = false }, containerColor = Lc.surface2) {
            why?.let { DropdownMenuItem(text = { SmallText(it, Lc.warn) }, onClick = {}, enabled = false) }
            @Composable fun item(region: ScanRegion, detail: String, enabled: Boolean) = DropdownMenuItem(
                text = { Column { Text(region.label, style = LcTypography.titleMedium); SmallText(detail, Lc.faint) } },
                leadingIcon = { Icon(when (region) { ScanRegion.AREAS -> LcIcons.rect; ScanRegion.MOTIF -> LcIcons.editor; ScanRegion.ALL -> LcIcons.scan }, null) },
                enabled = ready && enabled,
                onClick = { open = false; ws.scan(machine, editor, region) })
            item(ScanRegion.AREAS, if (areas.isEmpty()) "Noch keine Bereiche markiert" else "${areas.size} Bereich(e) – nur dort Bilder", areas.isNotEmpty())
            item(ScanRegion.MOTIF, if (doc.elements.isEmpty()) "Noch kein Motiv" else "Fläche unter dem Motiv + 1 cm Rand", doc.elements.isNotEmpty())
            item(ScanRegion.ALL, "Ganze Fläche 360 × 340 mm, dauert am längsten", true)
            if (onSetup != null) {
                HorizontalDivider(color = Lc.line)
                DropdownMenuItem(text = { Text("Bereiche markieren / Kamera …") }, leadingIcon = { Icon(LcIcons.camera, null) },
                    onClick = { open = false; onSetup() })
            }
        }
    }
}

/** Progress of a scan or calibration run with a cancel button (shown over the editor canvas). */
@Composable
fun RunStrip(ws: WorkspaceViewModel, modifier: Modifier = Modifier) {
    val run by ws.run.collectAsStateWithLifecycle()
    val r = run ?: return
    LcCard(modifier.widthIn(max = 360.dp), padding = 12.dp, accent = Lc.accent) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(r.title, style = LcTypography.titleMedium)
                SmallText(r.text)
            }
            LcButton("Abbrechen", { ws.cancel() }, kind = BtnKind.DANGER)
        }
        Spacer(Modifier.height(6.dp))
        Progress(r.fraction, Modifier.fillMaxWidth())
    }
}
