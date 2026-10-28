package de.millione.lumacut.app.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/* ---------- layout helpers ---------- */

/** Phone in portrait (and other narrow windows): stacked layouts, bottom navigation. */
@Composable
fun isCompact() = LocalConfiguration.current.screenWidthDp < 600

/** Soft tinted shadow on the light theme; the dark theme separates with a hairline instead. */
fun Modifier.lift(shape: Shape, elevation: Dp = 10.dp): Modifier =
    if (Lc.dark) this.border(1.dp, Lc.line, shape)
    else this.shadow(elevation, shape, clip = false, ambientColor = Lc.shadow, spotColor = Lc.shadow)

/**
 * Main area plus a side column. Wide: side by side, the side column [sideWidth] wide. Narrow (phone):
 * stacked, the main area gets [mainShare] of the height and the side column the rest; both keep
 * their own scrolling, so nothing is squeezed to zero width.
 */
@Composable
fun SplitPane(
    modifier: Modifier = Modifier,
    sideWidth: Dp = 380.dp,
    breakpoint: Dp = 760.dp,
    mainShare: Float = .42f,
    sideFirst: Boolean = false,
    main: @Composable (Modifier) -> Unit,
    side: @Composable (Modifier) -> Unit,
) {
    BoxWithConstraints(modifier.fillMaxSize()) {
        if (maxWidth >= breakpoint) Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            if (sideFirst) side(Modifier.width(sideWidth).fillMaxHeight())
            main(Modifier.weight(1f).fillMaxHeight())
            if (!sideFirst) side(Modifier.width(sideWidth).fillMaxHeight())
        } else Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (sideFirst) side(Modifier.fillMaxWidth().weight(1f - mainShare))
            main(Modifier.fillMaxWidth().weight(mainShare))
            if (!sideFirst) side(Modifier.fillMaxWidth().weight(1f - mainShare))
        }
    }
}

/** Page heading: optional step badge (1, 2, 3 of the main path), title and one line of help. */
@Composable
fun ScreenTitle(title: String, subtitle: String? = null, step: Int? = null, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        if (step != null) {
            Box(Modifier.size(34.dp).clip(CircleShape).background(Lc.accent), contentAlignment = Alignment.Center) {
                Text("$step", style = LcTypography.titleMedium, color = Lc.accentInk)
            }
            Spacer(Modifier.width(12.dp))
        }
        Column {
            Text(title, style = LcTypography.headlineSmall, color = Lc.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) Text(subtitle, style = LcTypography.bodyMedium, color = Lc.muted)
        }
    }
}

/* ---------- surfaces ---------- */

@Composable
fun LcCard(modifier: Modifier = Modifier, padding: Dp = 20.dp, accent: Color? = null, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    Column(modifier.lift(shape).clip(shape).background(Lc.surface)) {
        if (accent != null) Box(Modifier.fillMaxWidth().height(4.dp).background(accent))
        Column(Modifier.padding(padding), content = content)
    }
}

@Composable
fun Eyebrow(text: String) = Text(text.uppercase(), style = LcTypography.labelSmall, color = Lc.faint)

@Composable
fun CardTitle(title: String, modifier: Modifier = Modifier, trailing: @Composable RowScope.() -> Unit = {}) {
    Row(modifier.fillMaxWidth().padding(bottom = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = LcTypography.titleLarge, color = Lc.text, modifier = Modifier.weight(1f))
        trailing()
    }
}

/* ---------- buttons ---------- */

enum class BtnKind { PRIMARY, NORMAL, DANGER, GHOST }

@Composable
fun LcButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    kind: BtnKind = BtnKind.NORMAL,
    busy: Boolean = false,
    enabled: Boolean = true,
    big: Boolean = false,
) {
    val colors = when (kind) {
        BtnKind.PRIMARY -> ButtonDefaults.buttonColors(containerColor = Lc.accent, contentColor = Lc.accentInk,
            disabledContainerColor = Lc.accent.copy(alpha = .28f), disabledContentColor = Lc.accentInk.copy(alpha = .75f))
        BtnKind.DANGER -> ButtonDefaults.buttonColors(containerColor = Lc.bad.copy(alpha = .12f), contentColor = Lc.bad,
            disabledContainerColor = Lc.bad.copy(alpha = .06f), disabledContentColor = Lc.bad.copy(alpha = .45f))
        BtnKind.GHOST -> ButtonDefaults.buttonColors(containerColor = Color.Transparent, contentColor = Lc.text,
            disabledContainerColor = Color.Transparent, disabledContentColor = Lc.faint)
        BtnKind.NORMAL -> ButtonDefaults.buttonColors(containerColor = Lc.surface2, contentColor = Lc.text,
            disabledContainerColor = Lc.surface2, disabledContentColor = Lc.faint)
    }
    val border = when (kind) {
        BtnKind.NORMAL -> androidx.compose.foundation.BorderStroke(1.dp, Lc.line2)
        BtnKind.DANGER -> androidx.compose.foundation.BorderStroke(1.dp, Lc.bad.copy(alpha = .4f))
        else -> null
    }
    val shape = RoundedCornerShape(if (big) 20.dp else 16.dp)
    Button(
        onClick = onClick, enabled = enabled && !busy, colors = colors, border = border, shape = shape,
        contentPadding = PaddingValues(horizontal = if (big) 26.dp else 18.dp),
        modifier = modifier
            .then(if (kind == BtnKind.PRIMARY && enabled && !busy) Modifier.lift(shape, 8.dp) else Modifier)
            .heightIn(min = if (big) 64.dp else Lc.touch),
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = colors.contentColor)
            Spacer(Modifier.width(10.dp))
        } else if (icon != null) {
            Icon(icon, null, Modifier.size(if (big) 24.dp else 21.dp))
            Spacer(Modifier.width(10.dp))
        }
        Text(text, style = if (big) LcTypography.titleMedium else LcTypography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Round 48 dp icon button (ref.: soft round controls). */
@Composable
fun IconBtn(icon: ImageVector, label: String, onClick: () -> Unit, modifier: Modifier = Modifier,
            tint: Color = Lc.text, selected: Boolean = false, enabled: Boolean = true) {
    Box(
        modifier
            .size(48.dp)
            .clip(CircleShape)
            .background(if (selected) Lc.accentSoft else Lc.surface2)
            .border(1.dp, if (selected) Lc.accent.copy(alpha = .6f) else Lc.line, CircleShape)
            .clickable(enabled = enabled, onClickLabel = label, onClick = onClick)
            .alpha(if (enabled) 1f else .4f),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, label, tint = if (selected) Lc.accent else tint, modifier = Modifier.size(22.dp)) }
}

/* ---------- status ---------- */

@Composable
fun ToneChip(text: String, tone: Tone, modifier: Modifier = Modifier) {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val a by pulse.animateFloat(1f, .25f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")
    Row(
        modifier
            .height(36.dp)
            .clip(CircleShape)
            .background(if (tone == Tone.OFF || tone == Tone.OK) Lc.surface else tone.color.copy(alpha = .12f))
            .border(1.dp, if (tone == Tone.OFF || tone == Tone.OK) Lc.line else tone.color.copy(alpha = .35f), CircleShape)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(9.dp).alpha(if (tone == Tone.BUSY) a else 1f).clip(CircleShape).background(tone.color))
        Spacer(Modifier.width(8.dp))
        Text(text, style = LcTypography.labelMedium, color = if (tone == Tone.OK || tone == Tone.OFF) Lc.text else tone.color,
             maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun Tile(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = Lc.text) {
    Column(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(Lc.surface2)
            .padding(horizontal = 14.dp, vertical = 12.dp)
    ) {
        Text(label, style = LcTypography.bodySmall, color = Lc.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(3.dp))
        Text(value, style = LcTypography.titleMedium.merge(NumberStyle), color = valueColor, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Ring gauge with a big number in the middle (job progress, like a thermostat dial). */
@Composable
fun ProgressRing(fraction: Float, center: String, caption: String?, modifier: Modifier = Modifier, size: Dp = 132.dp, color: Color = Lc.accent) {
    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        val track = Lc.surface3
        Canvas(Modifier.fillMaxSize()) {
            val w = 10.dp.toPx()
            val inset = w / 2
            val arc = Size(this.size.width - w, this.size.height - w)
            drawArc(track, 135f, 270f, false, Offset(inset, inset), arc, style = Stroke(w, cap = StrokeCap.Round))
            drawArc(color, 135f, 270f * fraction.coerceIn(0f, 1f), false, Offset(inset, inset), arc, style = Stroke(w, cap = StrokeCap.Round))
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(center, style = LcTypography.headlineSmall.merge(NumberStyle), color = Lc.text)
            if (caption != null) Text(caption, style = LcTypography.bodySmall, color = Lc.muted, textAlign = TextAlign.Center)
        }
    }
}

/* ---------- inputs ---------- */

@Composable
fun <T> Segmented(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(if (Lc.dark) Lc.bg else Lc.surface3)
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for ((value, label) in options) {
            val on = value == selected
            val shape = RoundedCornerShape(12.dp)
            Box(
                Modifier
                    .heightIn(min = 44.dp)
                    .widthIn(min = 54.dp)
                    .then(if (on) Modifier.lift(shape, 3.dp) else Modifier)
                    .clip(shape)
                    .background(if (on) (if (Lc.dark) Lc.surface3 else Lc.surface) else Color.Transparent)
                    .clickable { onSelect(value) }
                    .padding(horizontal = 12.dp),
                contentAlignment = Alignment.Center,
            ) { Text(label, style = LcTypography.labelLarge, color = if (on) Lc.text else Lc.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) }
        }
    }
}

/** Tabs as pills with icons; scrolls sideways when the screen is narrow. */
@Composable
fun <T> PillTabs(options: List<Triple<T, String, ImageVector?>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    // Inner padding leaves room for the selected pill's shadow inside the scrolling row.
    Row(modifier.horizontalScroll(rememberScrollState()).padding(vertical = 8.dp, horizontal = 2.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for ((value, label, icon) in options) {
            val on = value == selected
            val shape = CircleShape
            Row(
                Modifier
                    .height(44.dp)
                    .then(if (on) Modifier.lift(shape, 6.dp) else Modifier)
                    .clip(shape)
                    .background(if (on) Lc.accent else Lc.surface)
                    .border(1.dp, if (on) Lc.accent else Lc.line, shape)
                    .clickable { onSelect(value) }
                    .padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (icon != null) { Icon(icon, null, tint = if (on) Lc.accentInk else Lc.muted, modifier = Modifier.size(19.dp)); Spacer(Modifier.width(8.dp)) }
                Text(label, style = LcTypography.labelLarge, color = if (on) Lc.accentInk else Lc.text, maxLines = 1)
            }
        }
    }
}

@Composable
fun ToggleTile(icon: ImageVector, label: String, on: Boolean, onToggle: () -> Unit, modifier: Modifier = Modifier, busy: Boolean = false) {
    Row(
        modifier
            .heightIn(min = 72.dp)
            .clip(RoundedCornerShape(20.dp))
            .background(if (on) Lc.accentSoft else Lc.surface2)
            .clickable(enabled = !busy, onClick = onToggle)
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(38.dp).clip(CircleShape).background(if (on) Lc.accent else Lc.surface), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = if (on) Lc.accentInk else Lc.muted, modifier = Modifier.size(20.dp))
        }
        Spacer(Modifier.width(12.dp))
        Text(label, style = LcTypography.labelLarge, color = Lc.text, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        Switch(checked = on, onCheckedChange = { onToggle() }, enabled = !busy, colors = lcSwitchColors())
    }
}

@Composable
fun lcSwitchColors() = SwitchDefaults.colors(
    checkedTrackColor = Lc.accent, checkedThumbColor = Lc.accentInk, checkedBorderColor = Lc.accent,
    uncheckedTrackColor = Lc.surface3, uncheckedThumbColor = Lc.faint, uncheckedBorderColor = Lc.line2,
)

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Lc.accent, unfocusedBorderColor = Lc.line2, focusedLabelColor = Lc.accent, unfocusedLabelColor = Lc.muted,
    focusedTextColor = Lc.text, unfocusedTextColor = Lc.text, cursorColor = Lc.accent,
    focusedContainerColor = Lc.surface, unfocusedContainerColor = Lc.surface,
)

@Composable
fun NumberField(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier = Modifier, suffix: String? = null) {
    OutlinedTextField(
        value = value, onValueChange = { v -> onChange(v.replace(',', '.').filter { it.isDigit() || it in ".-" }) },
        label = { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) }, singleLine = true, modifier = modifier,
        suffix = suffix?.let { { Text(it, color = Lc.muted, style = LcTypography.bodySmall) } },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        textStyle = LcTypography.bodyLarge.merge(NumberStyle),
        shape = RoundedCornerShape(14.dp),
        colors = fieldColors(),
    )
}

@Composable
fun TextInput(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier = Modifier, keyboard: KeyboardType = KeyboardType.Text) {
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true, modifier = modifier,
        keyboardOptions = KeyboardOptions(keyboardType = keyboard), shape = RoundedCornerShape(14.dp),
        colors = fieldColors(),
    )
}

@Composable
fun Progress(fraction: Float, modifier: Modifier = Modifier, thick: Boolean = false) {
    LinearProgressIndicator(
        progress = { fraction.coerceIn(0f, 1f) },
        modifier = modifier.height(if (thick) 12.dp else 8.dp).clip(CircleShape),
        color = Lc.accent, trackColor = Lc.surface3, drawStopIndicator = {},
    )
}

@Composable
fun Banner(text: String, color: Color = Lc.warn, modifier: Modifier = Modifier) {
    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(color.copy(alpha = .1f))
            .border(1.dp, color.copy(alpha = .3f), RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(LcIcons.warn, null, tint = color, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        // Text in the theme's ink, the tone shows in icon and frame: warm yellow text on white is hard to read.
        Text(text, style = LcTypography.bodyMedium, color = if (Lc.dark) color else Lc.text)
    }
}

/* ---------- dialogs ---------- */

/** Question waiting for the operator, shown as a modal sheet. */
data class Confirm(val title: String, val text: String, val yes: String = "OK", val danger: Boolean = false, val onYes: () -> Unit)

@Composable
fun ConfirmDialog(confirm: Confirm?, onDismiss: () -> Unit) {
    if (confirm == null) return
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Lc.surface,
        shape = RoundedCornerShape(28.dp),
        title = { Text(confirm.title, style = LcTypography.titleLarge, color = Lc.text) },
        text = { Text(confirm.text, style = LcTypography.bodyLarge, color = Lc.muted) },
        confirmButton = {
            LcButton(confirm.yes, { onDismiss(); confirm.onYes() }, kind = if (confirm.danger) BtnKind.DANGER else BtnKind.PRIMARY)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

@Composable
fun Labeled(label: String, content: @Composable () -> Unit) {
    Column {
        Text(label, style = LcTypography.bodySmall, color = Lc.muted)
        Spacer(Modifier.height(6.dp))
        content()
    }
}

@Composable
fun SmallText(text: String, color: Color = Lc.muted, modifier: Modifier = Modifier) =
    Text(text, style = LcTypography.bodySmall, color = color, modifier = modifier)

@Composable
fun Mono(text: String, modifier: Modifier = Modifier, color: Color = Lc.text) =
    Text(text, style = LcTypography.titleMedium.merge(NumberStyle).copy(fontWeight = FontWeight.SemiBold), color = color, modifier = modifier)

@Composable
fun rememberConfirm() = remember { mutableStateOf<Confirm?>(null) }

@Composable
fun OutlinedSmall(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) =
    OutlinedButton(onClick = onClick, modifier = modifier, shape = RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Lc.line2)) { Text(text, color = Lc.text) }

/** Floating dark pill for the tools that belong to the current selection (ref.: context tool bar). */
@Composable
fun ContextPill(modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) {
    val shape = RoundedCornerShape(22.dp)
    Row(
        modifier
            .shadow(14.dp, shape, ambientColor = Color.Black.copy(alpha = .3f), spotColor = Color.Black.copy(alpha = .3f))
            .clip(shape).background(Lc.ink).horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        content = content,
    )
}

/** Icon (+ optional short label) inside a [ContextPill]. */
@Composable
fun PillBtn(icon: ImageVector, label: String, onClick: () -> Unit, showLabel: Boolean = false, enabled: Boolean = true, tint: Color = Lc.onInk) {
    Row(
        Modifier
            .heightIn(min = 46.dp)
            .widthIn(min = 46.dp)
            .clip(RoundedCornerShape(14.dp))
            .clickable(enabled = enabled, onClickLabel = label, onClick = onClick)
            .alpha(if (enabled) 1f else .35f)
            .padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
    ) {
        Icon(icon, if (showLabel) null else label, tint = tint, modifier = Modifier.size(21.dp))
        if (showLabel) Text(label, style = LcTypography.labelMedium, color = tint, maxLines = 1)
    }
}

@Composable
fun PillDivider() = Box(Modifier.padding(horizontal = 4.dp).size(width = 1.dp, height = 24.dp).background(Lc.onInk.copy(alpha = .2f)))

/** Fills the available space with the editor's dotted background (ref.: dotted work surface). */
@Composable
fun DottedBackground(modifier: Modifier = Modifier) {
    val bg = Lc.canvas; val dot = Lc.dots
    Canvas(modifier.fillMaxSize()) {
        drawRect(bg)
        val step = 18.dp.toPx(); val r = 1.1.dp.toPx()
        var y = step / 2
        while (y < size.height) {
            var x = step / 2
            while (x < size.width) { drawCircle(dot, r, Offset(x, y)); x += step }
            y += step
        }
    }
}

/** Rounded, lifted surface with the dotted background for previews and canvases. */
@Composable
fun CanvasSurface(modifier: Modifier = Modifier, content: @Composable androidx.compose.foundation.layout.BoxScope.() -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    Box(modifier.lift(shape).clip(shape).background(Lc.canvas)) {
        DottedBackground()
        content()
    }
}
