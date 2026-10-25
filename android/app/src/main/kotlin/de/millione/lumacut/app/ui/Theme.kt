package de.millione.lumacut.app.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Design tokens. Dark workshop theme: calm surfaces, one accent, status by tone. */
object Lc {
    val bg = Color(0xFF090C11)
    val surface = Color(0xFF10151C)
    val surface2 = Color(0xFF161D26)
    val surface3 = Color(0xFF1D2631)
    val line = Color(0xFF243041)
    val line2 = Color(0xFF2F3D50)
    val text = Color(0xFFEEF3F8)
    val muted = Color(0xFF8E9DB0)
    val faint = Color(0xFF5C6B7E)
    val accent = Color(0xFF4FD8B4)
    val accentInk = Color(0xFF04261D)
    val accentSoft = Color(0x244FD8B4)
    val ok = accent
    val warn = Color(0xFFF2B45C)
    val bad = Color(0xFFFF6B70)
    val info = Color(0xFF6CB6FF)
    val cut = Color(0xFFFF7A59)
    val travel = Color(0xFF3A4A5E)
    val estop = Color(0xFFC9262F)
    val touch = 56.dp
}

enum class Tone(val color: Color) { OFF(Lc.faint), OK(Lc.ok), WARN(Lc.warn), BAD(Lc.bad), BUSY(Lc.accent) }

val LcTypography = Typography(
    displaySmall = TextStyle(fontSize = 30.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.6).sp),
    headlineSmall = TextStyle(fontSize = 24.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
    titleLarge = TextStyle(fontSize = 19.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.2).sp),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 14.5.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontSize = 12.5.sp, lineHeight = 17.sp),
    labelLarge = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp),
)

/** Numbers that must not jump while they change (positions, times). */
val NumberStyle = TextStyle(fontFeatureSettings = "tnum", fontWeight = FontWeight.SemiBold)

@Composable
fun LumaCutTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Lc.accent, onPrimary = Lc.accentInk,
            secondary = Lc.info, onSecondary = Lc.bg,
            background = Lc.bg, onBackground = Lc.text,
            surface = Lc.surface, onSurface = Lc.text,
            surfaceVariant = Lc.surface2, onSurfaceVariant = Lc.muted,
            surfaceContainer = Lc.surface2, surfaceContainerHigh = Lc.surface3,
            surfaceContainerHighest = Lc.surface3, surfaceContainerLow = Lc.surface,
            outline = Lc.line2, outlineVariant = Lc.line,
            error = Lc.bad, onError = Color.White,
        ),
        typography = LcTypography,
        shapes = Shapes(
            extraSmall = RoundedCornerShape(8.dp), small = RoundedCornerShape(12.dp),
            medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(20.dp), extraLarge = RoundedCornerShape(26.dp),
        ),
        content = content,
    )
}
