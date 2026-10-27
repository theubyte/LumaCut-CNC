package de.millione.lumacut.app.editor

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.ui.BarBtn
import de.millione.lumacut.app.ui.Confirm
import de.millione.lumacut.app.ui.ConfirmDialog
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.plateContent
import de.millione.lumacut.app.ui.rememberConfirm

/**
 * Plates of the project as one compact menu in the editor bar: switch, add one when the motif goes on
 * past one sheet, move the selection to another plate, remove a plate.
 */
@Composable
fun PlateMenu(editor: EditorViewModel, modifier: Modifier = Modifier) {
    val project by editor.project.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    var menu by remember { mutableStateOf(false) }
    var confirm by rememberConfirm()
    val active = project.activePlate
    val count = project.plateCount
    Box(modifier) {
        BarBtn(LcIcons.layers, if (count > 1) "Platte ${active + 1} / $count" else "Platte 1", { menu = true }, menu = true,
            description = "Platten")
        DropdownMenu(menu, { menu = false }, containerColor = Lc.surface2) {
            for (i in 0 until count) DropdownMenuItem(
                text = { Text("Platte ${i + 1} · ${plateContent(project.plateSize(i))}", color = if (i == active) Lc.accent else Lc.text) },
                leadingIcon = { if (i == active) Icon(LcIcons.check, null, tint = Lc.accent, modifier = Modifier.size(18.dp)) else Box(Modifier.size(18.dp)) },
                onClick = { menu = false; editor.setPlate(i) })
            HorizontalDivider(color = Lc.line)
            DropdownMenuItem(text = { Text("Weitere Platte anlegen") }, leadingIcon = { Icon(LcIcons.plus, null, modifier = Modifier.size(18.dp)) },
                onClick = { menu = false; editor.addPlate() })
            if (selected.isNotEmpty()) {
                for (i in 0 until count) if (i != active)
                    DropdownMenuItem(text = { Text("Auswahl auf Platte ${i + 1} verschieben") }, onClick = { menu = false; editor.moveSelectedToPlate(i) })
                DropdownMenuItem(text = { Text("Auswahl auf neue Platte verschieben") }, onClick = { menu = false; editor.moveSelectedToPlate(count) })
            }
            if (count > 1) DropdownMenuItem(text = { Text("Platte ${active + 1} löschen", color = Lc.bad) },
                leadingIcon = { Icon(LcIcons.trash, null, tint = Lc.bad, modifier = Modifier.size(18.dp)) }, onClick = {
                    menu = false
                    val n = project.plateSize(active)
                    if (n == 0) editor.deletePlate(active)
                    else confirm = Confirm("Platte ${active + 1} löschen?", "Die Platte und ihr Inhalt (${plateContent(n)}) werden entfernt. Rückgängig holt sie zurück.",
                        "Löschen", danger = true) { editor.deletePlate(active) }
                })
        }
    }
    ConfirmDialog(confirm) { confirm = null }
}
