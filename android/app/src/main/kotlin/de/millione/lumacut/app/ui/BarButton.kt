package de.millione.lumacut.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/** Compact 44 dp button for tool bars: icon, optional label, optional trailing ▾ for menus. */
@Composable
fun BarBtn(icon: ImageVector?, label: String?, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
           primary: Boolean = false, tint: Color = Lc.text, menu: Boolean = false, description: String? = label) {
    Row(
        modifier
            .height(44.dp)
            .widthIn(min = 44.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(if (primary) Lc.accent else Lc.surface2)
            .border(1.dp, if (primary) Lc.accent else Lc.line2, RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClickLabel = description, onClick = onClick)
            .alpha(if (enabled) 1f else .4f)
            .padding(horizontal = if (label == null) 10.dp else 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
    ) {
        val color = if (primary) Lc.accentInk else tint
        if (icon != null) Icon(icon, if (label == null) description else null, tint = color, modifier = Modifier.size(20.dp))
        if (label != null) Text(label, style = LcTypography.labelLarge, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (menu) Icon(LcIcons.chevronDown, null, tint = Lc.muted, modifier = Modifier.size(16.dp))
    }
}

/** Single-line 44 dp text field for tool bars (project name). */
@Composable
fun BarTextField(value: String, onChange: (String) -> Unit, modifier: Modifier = Modifier) {
    BasicTextField(
        value, onChange, singleLine = true, textStyle = LcTypography.titleMedium.copy(color = Lc.text),
        cursorBrush = SolidColor(Lc.accent), keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
        modifier = modifier.height(44.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xFF0C1117))
            .border(1.dp, Lc.line, RoundedCornerShape(12.dp)),
        decorationBox = { inner -> Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) { inner() } },
    )
}

/** Thin vertical divider between groups of bar buttons. */
@Composable
fun BarDivider() = Box(Modifier.size(width = 1.dp, height = 28.dp).background(Lc.line))
