package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import de.millione.lumacut.core.Document

/** "leer", "1 Teil", "5 Teile". */
fun plateContent(n: Int) = when (n) { 0 -> "leer"; 1 -> "1 Teil"; else -> "$n Teile" }

/** One chip per plate of [doc] with its number of parts; [done] plates get a check mark. */
@Composable
fun PlateChips(doc: Document, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier, done: Set<Int> = emptySet()) {
    Row(modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        for (i in 0 until doc.plateCount) {
            val on = i == selected
            Column(
                Modifier.heightIn(min = 48.dp).widthIn(min = 96.dp).clip(RoundedCornerShape(12.dp))
                    .background(if (on) Lc.accentSoft else Lc.surface)
                    .border(1.dp, if (on) Lc.accent.copy(alpha = .5f) else Lc.line, RoundedCornerShape(12.dp))
                    .clickable { onSelect(i) }.padding(horizontal = 14.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.Center,
            ) {
                Text("Platte ${i + 1}" + if (i in done) " ✓" else "", style = LcTypography.labelLarge, color = if (on) Lc.accent else Lc.text, maxLines = 1)
                Text(plateContent(doc.plateSize(i)), style = LcTypography.bodySmall, color = Lc.faint, maxLines = 1)
            }
        }
    }
}
