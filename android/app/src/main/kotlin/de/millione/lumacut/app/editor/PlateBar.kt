package de.millione.lumacut.app.editor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Confirm
import de.millione.lumacut.app.ui.ConfirmDialog
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.PlateChips
import de.millione.lumacut.app.ui.plateContent
import de.millione.lumacut.app.ui.rememberConfirm

/**
 * Plates of the project above the canvas: switch, add one when the motif goes on past one sheet,
 * move the selection to another plate, remove a plate.
 */
@Composable
fun PlateBar(editor: EditorViewModel, modifier: Modifier = Modifier) {
    val project by editor.project.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    var menu by remember { mutableStateOf(false) }
    var confirm by rememberConfirm()
    val active = project.activePlate
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        PlateChips(project, active, editor::setPlate, Modifier.weight(1f, fill = false))
        LcButton("Weitere Platte", editor::addPlate, icon = LcIcons.plus, kind = BtnKind.GHOST)
        Box {
            LcButton("Platten …", { menu = true }, kind = BtnKind.GHOST)
            DropdownMenu(menu, { menu = false }, containerColor = Lc.surface2) {
                for (i in 0 until project.plateCount) if (i != active)
                    DropdownMenuItem(text = { Text("Auswahl auf Platte ${i + 1} verschieben") }, enabled = selected.isNotEmpty(),
                        onClick = { menu = false; editor.moveSelectedToPlate(i) })
                DropdownMenuItem(text = { Text("Auswahl auf neue Platte verschieben") }, enabled = selected.isNotEmpty(),
                    onClick = { menu = false; editor.moveSelectedToPlate(project.plateCount) })
                DropdownMenuItem(text = { Text("Platte ${active + 1} löschen", color = if (project.plateCount > 1) Lc.bad else Lc.muted) },
                    enabled = project.plateCount > 1, onClick = {
                        menu = false
                        val n = project.plateSize(active)
                        if (n == 0) editor.deletePlate(active)
                        else confirm = Confirm("Platte ${active + 1} löschen?", "Die Platte und ihr Inhalt (${plateContent(n)}) werden entfernt. Rückgängig holt sie zurück.",
                            "Löschen", danger = true) { editor.deletePlate(active) }
                    })
            }
        }
    }
    ConfirmDialog(confirm) { confirm = null }
}
