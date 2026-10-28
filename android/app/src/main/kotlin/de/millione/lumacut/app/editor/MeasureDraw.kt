package de.millione.lumacut.app.editor

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.WorkMapper
import de.millione.lumacut.core.MeasureView
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.SnapHit
import de.millione.lumacut.core.SnapKind
import kotlin.math.atan2
import kotlin.math.hypot

// Darker amber and green on the light sheet: the bright ones of the dark theme vanish on white.
private val MEASURE_COLOR get() = if (Lc.dark) Color(0xFFFFC857) else Color(0xFFB86500)
private val STALE_COLOR = Color(0xFF8892A0)
private val SNAP_COLOR get() = if (Lc.dark) Color(0xFF5BE3A1) else Color(0xFF0E8F62)

private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 30f; typeface = Typeface.DEFAULT_BOLD }

/** Text on a dark pill, always the same size on screen; kept inside the canvas. */
private fun DrawScope.pillText(text: String, centre: Offset, color: Color) {
    textPaint.color = color.toArgb()
    val w = textPaint.measureText(text)
    val h = textPaint.textSize
    val x = (centre.x - w / 2).coerceIn(6f, (size.width - w - 6f).coerceAtLeast(6f))
    val y = (centre.y + h / 3).coerceIn(h + 4f, size.height - 6f)
    drawRoundRect(Color(0xE60B1015), Offset(x - 8f, y - h), Size(w + 16f, h + 12f), androidx.compose.ui.geometry.CornerRadius(10f, 10f))
    drawContext.canvas.nativeCanvas.drawText(text, x, y, textPaint)
}

/** All measurements as lines, dots, boxes and labels; the [selected] one is drawn heavier. */
fun DrawScope.drawMeasurements(m: WorkMapper, views: List<Pair<String, MeasureView>>, selected: String?) {
    for ((id, v) in views) {
        val color = if (v.stale) STALE_COLOR else MEASURE_COLOR
        val heavy = id == selected
        val o = v.overlay
        for (b in o.boxes) {
            val a = m.at(Pt(b.minX, b.minY)); val c = m.at(Pt(b.maxX, b.maxY))
            drawRect(color.copy(alpha = .7f), a, Size(c.x - a.x, c.y - a.y), style = Stroke(if (heavy) 3f else 1.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
        }
        for ((a, b) in o.dashed) drawLine(color.copy(alpha = .5f), m.at(a), m.at(b), 1.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 6f)))
        for ((a, b) in o.segs) {
            if (heavy) drawLine(Lc.sheet.copy(alpha = .6f), m.at(a), m.at(b), 6f, StrokeCap.Round)
            drawLine(color, m.at(a), m.at(b), if (heavy) 3.5f else 2.5f, StrokeCap.Round)
        }
        o.arc?.let { arc ->
            val v0 = m.at(arc.vertex); val f = m.at(arc.from); val t = m.at(arc.to)
            val r = hypot(f.x - v0.x, f.y - v0.y)
            val a1 = Math.toDegrees(atan2((f.y - v0.y).toDouble(), (f.x - v0.x).toDouble())).toFloat()
            val a2 = Math.toDegrees(atan2((t.y - v0.y).toDouble(), (t.x - v0.x).toDouble())).toFloat()
            var sweep = a2 - a1
            while (sweep > 180f) sweep -= 360f
            while (sweep < -180f) sweep += 360f
            drawArc(color, a1, sweep, false, Offset(v0.x - r, v0.y - r), Size(2 * r, 2 * r), style = Stroke(if (heavy) 3.5f else 2.5f))
        }
        for (p in o.dots) { val c = m.at(p); drawCircle(Lc.bg, 7f, c); drawCircle(color, 5f, c) }
        for (l in o.labels) pillText(if (v.stale) l.text + " (veraltet)" else l.text, m.at(l.at), color)
    }
}

/** Marker for a caught point; the shape tells the kind (corner square, centre cross, midpoint diamond, edge dot). */
fun DrawScope.drawSnapMarker(at: Offset, kind: SnapKind) {
    val r = 11f
    when (kind) {
        SnapKind.CORNER -> drawRect(SNAP_COLOR, Offset(at.x - r, at.y - r), Size(2 * r, 2 * r), style = Stroke(3f))
        SnapKind.CENTER -> { drawCircle(SNAP_COLOR, r, at, style = Stroke(3f)); drawLine(SNAP_COLOR, Offset(at.x - r, at.y), Offset(at.x + r, at.y), 2f); drawLine(SNAP_COLOR, Offset(at.x, at.y - r), Offset(at.x, at.y + r), 2f) }
        SnapKind.MID -> drawPath(Path().apply { moveTo(at.x, at.y - r); lineTo(at.x + r, at.y); lineTo(at.x, at.y + r); lineTo(at.x - r, at.y); close() }, SNAP_COLOR, style = Stroke(3f))
        SnapKind.EDGE -> drawCircle(SNAP_COLOR, 7f, at)
    }
}

/**
 * Magnifier above the finger: the scene around [finger] at 3× with a crosshair in the middle and the kind of the
 * caught point underneath. [scene] draws everything that is magnified (work area, shapes, measurements).
 */
fun DrawScope.drawLoupe(finger: Offset, hit: SnapHit?, hitAt: Offset?, snapping: Boolean, radiusPx: Float, scene: DrawScope.() -> Unit) {
    val zoom = 3f
    val gap = radiusPx * 0.9f
    var c = Offset(finger.x, finger.y - radiusPx - gap)
    if (c.y - radiusPx < 4f) c = Offset(finger.x + (if (finger.x < size.width / 2) 1 else -1) * (radiusPx + gap), (finger.y).coerceAtLeast(radiusPx + 4f))
    c = Offset(c.x.coerceIn(radiusPx + 4f, size.width - radiusPx - 4f), c.y.coerceIn(radiusPx + 4f, size.height - radiusPx - 4f))
    val clip = Path().apply { addOval(Rect(c, radiusPx)) }
    clipPath(clip) {
        drawRect(Lc.canvas, Offset(c.x - radiusPx, c.y - radiusPx), Size(2 * radiusPx, 2 * radiusPx))
        withTransform({ translate(c.x - finger.x, c.y - finger.y); scale(zoom, zoom, pivot = finger) }) { scene() }
        // the caught point is where the crosshair points: show it magnified too
        if (hit != null && hitAt != null) drawSnapMarker(Offset(c.x + (hitAt.x - finger.x) * zoom, c.y + (hitAt.y - finger.y) * zoom), hit.kind)
    }
    drawCircle(Lc.bg, radiusPx + 3f, c, style = Stroke(6f))
    drawCircle(MEASURE_COLOR, radiusPx, c, style = Stroke(3f))
    val arm = 14f
    for ((dx, dy) in listOf(1f to 0f, -1f to 0f, 0f to 1f, 0f to -1f)) {
        drawLine(MEASURE_COLOR, Offset(c.x + dx * arm * 0.6f, c.y + dy * arm * 0.6f), Offset(c.x + dx * arm * 2.2f, c.y + dy * arm * 2.2f), 2.5f)
    }
    val label = when {
        !snapping -> "frei"
        hit == null -> "frei"
        else -> hit.kind.label
    }
    pillText(label, Offset(c.x, c.y + radiusPx + 26f), if (hit == null) Color.White else SNAP_COLOR)
}
