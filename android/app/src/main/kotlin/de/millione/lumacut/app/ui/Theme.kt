package de.millione.lumacut.app.ui

import android.content.Context
import android.content.res.Configuration
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** One set of colours. Light: lavender-white workshop with an indigo accent; dark: the same calm on near-black. */
class LcPalette(
    val dark: Boolean,
    val bg: Color, val surface: Color, val surface2: Color, val surface3: Color,
    val line: Color, val line2: Color,
    val text: Color, val muted: Color, val faint: Color,
    val accent: Color, val accentInk: Color, val accentSoft: Color,
    val ok: Color, val warn: Color, val bad: Color, val info: Color,
    val cut: Color, val travel: Color, val estop: Color,
    /** Editor/preview background around the work area, its dot grid, and the work area ("sheet") itself. */
    val canvas: Color, val dots: Color, val sheet: Color, val grid: Color, val gridMajor: Color,
    /** Floating dark pill (context tool bar) and the text on it. */
    val ink: Color, val onInk: Color,
    val shadow: Color,
)

val LightPalette = LcPalette(
    dark = false,
    bg = Color(0xFFF2F3F9), surface = Color(0xFFFFFFFF), surface2 = Color(0xFFF4F5FB), surface3 = Color(0xFFE8EAF5),
    line = Color(0xFFE2E5F0), line2 = Color(0xFFCDD2E4),
    text = Color(0xFF151827), muted = Color(0xFF555B73), faint = Color(0xFF62687F),
    accent = Color(0xFF4A57E3), accentInk = Color(0xFFFFFFFF), accentSoft = Color(0x1A4A57E3),
    ok = Color(0xFF12855A), warn = Color(0xFFAD6500), bad = Color(0xFFCF3340), info = Color(0xFF2C68D6),
    cut = Color(0xFFE2552D), travel = Color(0xFFB4BBD2), estop = Color(0xFFD7262F),
    canvas = Color(0xFFECEEF7), dots = Color(0xFFC6CBE0), sheet = Color(0xFFFFFFFF), grid = Color(0x14404A80), gridMajor = Color(0x2E404A80),
    ink = Color(0xFF161929), onInk = Color(0xFFF4F5FB),
    shadow = Color(0x334A57E3),
)

val DarkPalette = LcPalette(
    dark = true,
    bg = Color(0xFF0E1016), surface = Color(0xFF171A23), surface2 = Color(0xFF1E2230), surface3 = Color(0xFF282D3E),
    line = Color(0xFF272C3B), line2 = Color(0xFF363C51),
    text = Color(0xFFEEF0F8), muted = Color(0xFFA6ACC2), faint = Color(0xFF8C92AA),
    accent = Color(0xFF8F9BFF), accentInk = Color(0xFF0D113D), accentSoft = Color(0x2B8F9BFF),
    ok = Color(0xFF4FD8A4), warn = Color(0xFFF2B45C), bad = Color(0xFFFF6B70), info = Color(0xFF6CB6FF),
    cut = Color(0xFFFF7A59), travel = Color(0xFF3B4358), estop = Color(0xFFC9262F),
    canvas = Color(0xFF0A0C11), dots = Color(0xFF242938), sheet = Color(0xFF131722), grid = Color(0x16A6ACC2), gridMajor = Color(0x30A6ACC2),
    ink = Color(0xFF2A3045), onInk = Color(0xFFF1F2F8),
    shadow = Color(0x00000000),
)

/**
 * Design tokens. They read the current palette (snapshot state), so composables and canvases
 * follow a switch between light and dark at once.
 */
object Lc {
    var palette by mutableStateOf(LightPalette)
    val dark get() = palette.dark
    val bg get() = palette.bg
    val surface get() = palette.surface
    val surface2 get() = palette.surface2
    val surface3 get() = palette.surface3
    val line get() = palette.line
    val line2 get() = palette.line2
    val text get() = palette.text
    val muted get() = palette.muted
    val faint get() = palette.faint
    val accent get() = palette.accent
    val accentInk get() = palette.accentInk
    val accentSoft get() = palette.accentSoft
    val ok get() = palette.ok
    val warn get() = palette.warn
    val bad get() = palette.bad
    val info get() = palette.info
    val cut get() = palette.cut
    val travel get() = palette.travel
    val estop get() = palette.estop
    val canvas get() = palette.canvas
    val dots get() = palette.dots
    val sheet get() = palette.sheet
    val grid get() = palette.grid
    val gridMajor get() = palette.gridMajor
    val ink get() = palette.ink
    val onInk get() = palette.onInk
    val shadow get() = palette.shadow
    val touch = 56.dp
}

enum class Tone {
    OFF, OK, WARN, BAD, BUSY;
    val color: Color get() = when (this) { OFF -> Lc.faint; OK -> Lc.ok; WARN -> Lc.warn; BAD -> Lc.bad; BUSY -> Lc.accent }
}

/** Light, dark, or as the system says. A per-device choice, so it lives on the device, not on the Pi. */
enum class ThemeMode(val label: String) {
    SYSTEM("Wie System"), LIGHT("Hell"), DARK("Dunkel");

    companion object {
        private const val KEY = "theme_mode"
        fun load(ctx: Context): ThemeMode =
            runCatching { valueOf(ctx.getSharedPreferences("lumacut", Context.MODE_PRIVATE).getString(KEY, null) ?: "SYSTEM") }.getOrDefault(SYSTEM)

        fun resolve(ctx: Context, mode: ThemeMode = load(ctx)): LcPalette = when (mode) {
            LIGHT -> LightPalette
            DARK -> DarkPalette
            SYSTEM -> if ((ctx.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES) DarkPalette else LightPalette
        }

        /** Saves [mode] and switches the palette right away. */
        fun apply(ctx: Context, mode: ThemeMode) {
            ctx.getSharedPreferences("lumacut", Context.MODE_PRIVATE).edit().putString(KEY, mode.name).apply()
            Lc.palette = resolve(ctx, mode)
        }
    }
}

val LcTypography = Typography(
    displaySmall = TextStyle(fontSize = 30.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.6).sp),
    headlineSmall = TextStyle(fontSize = 24.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
    titleLarge = TextStyle(fontSize = 19.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.2).sp),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 14.5.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontSize = 13.sp, lineHeight = 18.sp),
    labelLarge = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.2.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp),
)

/** Numbers that must not jump while they change (positions, times). */
val NumberStyle = TextStyle(fontFeatureSettings = "tnum", fontWeight = FontWeight.SemiBold)

@Composable
fun LumaCutTheme(content: @Composable () -> Unit) {
    val p = Lc.palette
    val scheme = if (p.dark) darkColorScheme(
        primary = p.accent, onPrimary = p.accentInk, secondary = p.info, onSecondary = p.bg,
        background = p.bg, onBackground = p.text, surface = p.surface, onSurface = p.text,
        surfaceVariant = p.surface2, onSurfaceVariant = p.muted, surfaceContainer = p.surface2, surfaceContainerHigh = p.surface3,
        surfaceContainerHighest = p.surface3, surfaceContainerLow = p.surface, outline = p.line2, outlineVariant = p.line,
        error = p.bad, onError = Color.White,
    ) else lightColorScheme(
        primary = p.accent, onPrimary = p.accentInk, secondary = p.info, onSecondary = Color.White,
        background = p.bg, onBackground = p.text, surface = p.surface, onSurface = p.text,
        surfaceVariant = p.surface2, onSurfaceVariant = p.muted, surfaceContainer = p.surface, surfaceContainerHigh = p.surface,
        surfaceContainerHighest = p.surface3, surfaceContainerLow = p.surface2, outline = p.line2, outlineVariant = p.line,
        error = p.bad, onError = Color.White,
    )
    MaterialTheme(
        colorScheme = scheme,
        typography = LcTypography,
        shapes = Shapes(
            extraSmall = RoundedCornerShape(8.dp), small = RoundedCornerShape(12.dp),
            medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(22.dp), extraLarge = RoundedCornerShape(28.dp),
        ),
    ) {
        // Text without an explicit colour follows the palette (before, it fell back to black on the dark theme).
        CompositionLocalProvider(LocalContentColor provides p.text, content = content)
    }
}
