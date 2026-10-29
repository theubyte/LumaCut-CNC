package de.millione.lumacut.app.editor

import android.os.Build
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.core.SavedProject
import de.millione.lumacut.core.SavedProjects
import kotlinx.coroutines.launch

/**
 * Projects saved on the Pi (/api/projects): open one into the editor, or
 * save the open project under a name. Every device sees the same list.
 */
@Composable
internal fun PiProjectsDialog(machine: MachineViewModel, editor: EditorViewModel, save: Boolean, onDismiss: () -> Unit) {
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<List<SavedProject>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf(editor.doc.value.title) }
    var deleting by remember { mutableStateOf<SavedProject?>(null) }
    val device = (Build.MODEL ?: "Gerät").take(40)

    fun reload() = scope.launch {
        val c = machine.clientOrNotify() ?: run { onDismiss(); return@launch }
        runCatching { c.savedProjects() }.onSuccess { list = it; error = null }
            .onFailure { error = if (SavedProjects.FEATURE !in (machine.status.value?.features ?: emptyList()))
                "Der Pi kann noch keine Projekte speichern – Pi-Software aktualisieren." else it.message ?: "Liste nicht lesbar" }
    }
    LaunchedEffect(Unit) { reload() }

    fun open(p: SavedProject) = scope.launch {
        val c = machine.clientOrNotify() ?: return@launch
        busy = true
        runCatching { c.savedProject(p.id) }
            .onSuccess { editor.openJson(it); onDismiss() }
            .onFailure { machine.notify(it.message ?: "Projekt nicht lesbar", true) }
        busy = false
    }

    fun store() = scope.launch {
        val c = machine.clientOrNotify() ?: return@launch
        busy = true
        val title = name.trim()
        // the saved name becomes the project title, so the next save offers it again
        if (title != editor.doc.value.title) editor.rename(title)
        runCatching { c.saveProjectAs(title, editor.projectJson(), device) }
            .onSuccess { machine.notify(if (it.replaced) "„${it.name}“ auf dem Pi ersetzt" else "„${it.name}“ auf dem Pi gespeichert"); onDismiss() }
            .onFailure { machine.notify(it.message ?: "Speichern fehlgeschlagen", true) }
        busy = false
    }

    fun remove(p: SavedProject) = scope.launch {
        val c = machine.clientOrNotify() ?: return@launch
        runCatching { c.deleteSavedProject(p.id) }
            .onSuccess { machine.notify("„${p.name}“ gelöscht"); reload() }
            .onFailure { machine.notify(it.message ?: "Löschen fehlgeschlagen", true) }
    }

    val existing = list?.let { SavedProjects.named(it, name) }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text(if (save) "Auf dem Pi speichern" else "Projekt vom Pi öffnen", style = LcTypography.titleLarge, color = Lc.text) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (save) {
                    TextInput("Name", name, { name = it }, Modifier.fillMaxWidth())
                    if (existing != null) SmallText("Ein Projekt „${existing.name}“ gibt es schon – Speichern ersetzt es.", Lc.warn)
                }
                when {
                    error != null -> SmallText(error!!, Lc.bad)
                    list == null -> SmallText("Liste wird geladen …")
                    list!!.isEmpty() -> SmallText("Noch keine Projekte auf dem Pi.")
                    else -> {
                        if (save) SmallText("Schon auf dem Pi (antippen übernimmt den Namen):")
                        LazyColumn(Modifier.heightIn(max = 360.dp)) {
                            items(list!!, key = { it.id }) { p ->
                                Row(Modifier.fillMaxWidth().clickable(enabled = !busy) { if (save) name = p.name else open(p) }
                                    .padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f)) {
                                        Text(p.name, style = LcTypography.bodyLarge, color = Lc.text)
                                        SmallText(SavedProjects.line(p))
                                    }
                                    IconButton({ deleting = p }, enabled = !busy) { Icon(LcIcons.trash, "„${p.name}“ löschen", tint = Lc.muted) }
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            if (save) LcButton(if (existing != null) "Ersetzen" else "Speichern", { store() }, icon = LcIcons.save,
                kind = BtnKind.PRIMARY, busy = busy, enabled = name.isNotBlank() && error == null && list != null)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(if (save) "Abbrechen" else "Schließen", color = Lc.muted) } },
    )
    deleting?.let { p ->
        AlertDialog(
            onDismissRequest = { deleting = null }, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
            title = { Text("„${p.name}“ löschen?", style = LcTypography.titleLarge, color = Lc.text) },
            text = { Text("Das Projekt verschwindet vom Pi und damit von allen Geräten.", style = LcTypography.bodyLarge, color = Lc.muted) },
            confirmButton = { LcButton("Löschen", { deleting = null; remove(p) }, kind = BtnKind.DANGER) },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Abbrechen", color = Lc.muted) } },
        )
    }
}
