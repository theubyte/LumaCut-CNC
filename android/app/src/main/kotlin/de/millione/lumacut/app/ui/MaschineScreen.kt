package de.millione.lumacut.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.workspace.CalibrationScreen
import de.millione.lumacut.app.workspace.WorkspaceScreen

enum class MachineTab(val label: String) {
    STEUERUNG("Steuerung"), SCAN("Arbeitsplatz scannen"), KALIBRIEREN("Kalibrieren"), AUFTRAEGE("Aufträge auf dem Pi"),
}

/** Everything a beginner never needs: jog, probe, job list, workplace scan and the calibrations. */
@Composable
fun MaschineScreen(machine: MachineViewModel, editor: EditorViewModel, tab: MachineTab, onTab: (MachineTab) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(start = 16.dp, top = 12.dp, end = 16.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Segmented(MachineTab.entries.map { it to it.label }, tab, onTab)
        }
        Box(Modifier.fillMaxSize()) {
            when (tab) {
                MachineTab.STEUERUNG -> WerkstattScreen(machine)
                MachineTab.SCAN -> WorkspaceScreen(machine, editor)
                MachineTab.KALIBRIEREN -> CalibrationScreen(machine)
                MachineTab.AUFTRAEGE -> JobsScreen(machine)
            }
        }
    }
}
