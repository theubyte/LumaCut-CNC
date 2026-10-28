package de.millione.lumacut.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.workspace.CalibrationScreen
import de.millione.lumacut.app.workspace.WorkspaceScreen

enum class MachineTab(val label: String, val icon: ImageVector) {
    STEUERUNG("Steuerung", LcIcons.machine), SCAN("Arbeitsplatz scannen", LcIcons.scan),
    KALIBRIEREN("Kalibrieren", LcIcons.ruler), AUFTRAEGE("Aufträge auf dem Pi", LcIcons.jobs),
}

/** Everything a beginner never needs: jog, probe, job list, workplace scan and the calibrations. */
@Composable
fun MaschineScreen(machine: MachineViewModel, editor: EditorViewModel, tab: MachineTab, onTab: (MachineTab) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        PillTabs(MachineTab.entries.map { Triple(it, it.label, it.icon) }, tab, onTab,
            Modifier.fillMaxWidth().padding(start = 16.dp, top = 4.dp, end = 16.dp, bottom = 4.dp))
        Box(Modifier.fillMaxSize()) {
            when (tab) {
                MachineTab.STEUERUNG -> WerkstattScreen(machine)
                MachineTab.SCAN -> WorkspaceScreen(machine, editor)
                MachineTab.KALIBRIEREN -> CalibrationScreen(machine, editor)
                MachineTab.AUFTRAEGE -> JobsScreen(machine)
            }
        }
    }
}
