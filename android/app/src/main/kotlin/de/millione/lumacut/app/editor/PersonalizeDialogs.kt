package de.millione.lumacut.app.editor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.core.Personalize
import de.millione.lumacut.core.TagStyle

private fun num(s: String) = s.replace(',', '.').toDoubleOrNull()

@Composable
private fun PDialog(title: String, action: String, valid: Boolean, onDismiss: () -> Unit, onApply: () -> Unit, content: @Composable () -> Unit) =
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text(title, style = LcTypography.titleLarge) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) { content() } },
        confirmButton = { LcButton(action, { onApply(); onDismiss() }, kind = BtnKind.PRIMARY, enabled = valid) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )

/** Name tags / keychains for a whole list of names (one per line), like LightBurn's variable text. */
@Composable
fun TagsDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var names by remember { mutableStateOf("") }
    var style by remember { mutableStateOf(TagStyle.KEYCHAIN) }
    var height by remember { mutableStateOf("12") }
    var bold by remember { mutableStateOf(true) }
    var hole by remember { mutableStateOf(true) }
    val list = names.lines().map { it.trim() }.filter { it.isNotEmpty() }
    val valid = list.isNotEmpty() && list.size <= 100 && num(height)?.let { it in 4.0..80.0 } == true
    PDialog("Namensschilder & Anhänger", if (list.size > 1) "${list.size} erzeugen" else "Erzeugen", valid, onDismiss, {
        editor.addTags(list, style, num(height)!!, bold, if (hole) 4.0 else null)
    }) {
        OutlinedTextField(names, { names = it }, label = { Text("Namen – einer pro Zeile") }, minLines = 3, maxLines = 8,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Lc.accent, unfocusedBorderColor = Lc.line2, focusedLabelColor = Lc.accent))
        Segmented(TagStyle.entries.map { it to it.label.substringBefore(" (") }, style, { style = it }, Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Schrifthöhe", height, { height = it }, Modifier.weight(1f), "mm")
            Segmented(listOf(true to "Fett", false to "Normal"), bold, { bold = it }, Modifier.weight(1f))
        }
        Segmented(listOf(true to "Mit Loch (4 mm)", false to "Ohne Loch"), hole, { hole = it }, Modifier.fillMaxWidth())
        SmallText("Name wird graviert, Umriss und Loch geschnitten. Die Teile werden platzsparend angeordnet; " +
            "ist die Platte schon belegt oder voll, geht es auf neuen Platten weiter.", Lc.faint)
    }
}

/** Round emblem with initials and text along the edge (monogram, gift, door sign). */
@Composable
fun EmblemDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var initials by remember { mutableStateOf("") }
    var top by remember { mutableStateOf("") }
    var bottom by remember { mutableStateOf("") }
    var diameter by remember { mutableStateOf("80") }
    val valid = initials.isNotBlank() && initials.length <= 6 && num(diameter)?.let { it in 30.0..330.0 } == true
    PDialog("Monogramm-Emblem", "Erzeugen", valid, onDismiss, { editor.addEmblem(initials, top, bottom, num(diameter)!!) }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextInput("Initialen (z. B. A&M)", initials, { initials = it }, Modifier.weight(1f))
            NumberField("Durchmesser", diameter, { diameter = it }, Modifier.weight(1f), "mm")
        }
        TextInput("Text oben (optional, z. B. Familie Müller)", top, { top = it }, Modifier.fillMaxWidth())
        TextInput("Text unten (optional, z. B. Datum)", bottom, { bottom = it }, Modifier.fillMaxWidth())
        SmallText("Außenkreis wird geschnitten, Ringe markiert, Schrift graviert. Lange Texte werden passend verkleinert.", Lc.faint)
    }
}

/** Frame around the selection or around everything on the plate. */
@Composable
fun FrameDialog(editor: EditorViewModel, hasSelection: Boolean, onDismiss: () -> Unit) {
    var style by remember { mutableStateOf(Personalize.FrameStyle.ROUNDED) }
    var margin by remember { mutableStateOf("5") }
    var cut by remember { mutableStateOf(true) }
    val valid = num(margin)?.let { it in 0.0..100.0 } == true
    PDialog("Rahmen", "Rahmen setzen", valid, onDismiss, { editor.addFrame(style, num(margin)!!, cut) }) {
        Segmented(Personalize.FrameStyle.entries.map { it to it.label }, style, { style = it }, Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Abstand zum Motiv", margin, { margin = it }, Modifier.weight(1f), "mm")
            Segmented(listOf(true to "Schneiden", false to "Markieren"), cut, { cut = it }, Modifier.weight(1f))
        }
        SmallText(if (hasSelection) "Der Rahmen kommt um die Auswahl." else "Der Rahmen kommt um alles auf dieser Platte.", Lc.faint)
    }
}

/** Ruler with mm ticks and cm numbers. */
@Composable
fun RulerDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var length by remember { mutableStateOf("150") }
    var width by remember { mutableStateOf("30") }
    var hole by remember { mutableStateOf(true) }
    val valid = length.toIntOrNull()?.let { it in 30..320 } == true && num(width)?.let { it in 15.0..80.0 } == true
    PDialog("Lineal", "Erzeugen", valid, onDismiss, { editor.addRuler(length.toInt(), num(width)!!, if (hole) 5.0 else null) }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Messlänge", length, { length = it }, Modifier.weight(1f), "mm")
            NumberField("Breite", width, { width = it }, Modifier.weight(1f), "mm")
        }
        Segmented(listOf(true to "Mit Aufhängeloch", false to "Ohne Loch"), hole, { hole = it }, Modifier.fillMaxWidth())
        SmallText("Striche werden markiert (Ebene Linie), Zahlen graviert, Umriss geschnitten. Ideal als Geschenk mit Namen – " +
            "einfach noch einen Text daraufsetzen.", Lc.faint)
    }
}

/** Jigsaw puzzle: over the selection (e.g. a photo) or as a new piece. */
@Composable
fun PuzzleDialog(editor: EditorViewModel, hasSelection: Boolean, onDismiss: () -> Unit) {
    var cols by remember { mutableStateOf("4") }
    var rows by remember { mutableStateOf("3") }
    var w by remember { mutableStateOf("160") }
    var h by remember { mutableStateOf("120") }
    val valid = cols.toIntOrNull()?.let { it in 2..30 } == true && rows.toIntOrNull()?.let { it in 2..30 } == true &&
        (hasSelection || (num(w)?.let { it in 30.0..360.0 } == true && num(h)?.let { it in 30.0..340.0 } == true))
    PDialog("Puzzle", "Puzzle erzeugen", valid, onDismiss, {
        editor.addPuzzle(cols.toInt(), rows.toInt(), num(w) ?: 160.0, num(h) ?: 120.0)
    }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Teile waagrecht", cols, { cols = it }, Modifier.weight(1f))
            NumberField("Teile senkrecht", rows, { rows = it }, Modifier.weight(1f))
        }
        if (!hasSelection) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Breite", w, { w = it }, Modifier.weight(1f), "mm")
            NumberField("Höhe", h, { h = it }, Modifier.weight(1f), "mm")
        }
        SmallText(if (hasSelection) "Das Puzzle wird genau über die Auswahl gelegt – z. B. ein Foto: erst gravieren, dann schneiden."
                  else "Tipp: erst ein Foto importieren und auswählen, dann wird es zum Fotopuzzle.", Lc.faint)
    }
}
