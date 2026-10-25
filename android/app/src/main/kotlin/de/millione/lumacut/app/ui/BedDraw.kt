package de.millione.lumacut.app.ui

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import de.millione.lumacut.core.Bed
import de.millione.lumacut.core.Pt
import kotlin.math.min

/**
 * Maps machine millimetres to screen pixels. [originBottom] puts X0/Y0 at
 * the bottom-left (machine Y up); otherwise top-left (Y down). Machine
 * coordinates themselves never change.
 */
class BedMapper(val scale: Float, val ox: Float, val oy: Float, val originBottom: Boolean) {
    fun x(mm: Double): Float = ox + mm.toFloat() * scale
    fun y(mm: Double): Float = oy + (if (originBottom) Bed.HEIGHT - mm else mm).toFloat() * scale
    fun at(p: Pt) = Offset(x(p.x), y(p.y))
    fun at(xMm: Float, yMm: Float) = Offset(ox + xMm * scale, oy + (if (originBottom) Bed.HEIGHT.toFloat() - yMm else yMm) * scale)
    fun toBed(o: Offset): Pt {
        val yy = ((o.y - oy) / scale).toDouble()
        return Pt(((o.x - ox) / scale).toDouble(), if (originBottom) Bed.HEIGHT - yy else yy)
    }
    fun mm(px: Float) = px / scale

    companion object {
        fun fit(size: Size, originBottom: Boolean, padding: Float = 24f, zoom: Float = 1f, pan: Offset = Offset.Zero): BedMapper {
            val base = min((size.width - 2 * padding) / Bed.WIDTH.toFloat(), (size.height - 2 * padding) / Bed.HEIGHT.toFloat())
            val k = base * zoom
            val ox = (size.width - Bed.WIDTH.toFloat() * k) / 2 + pan.x
            val oy = (size.height - Bed.HEIGHT.toFloat() * k) / 2 + pan.y
            return BedMapper(k, ox, oy, originBottom)
        }
    }
}

private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 28f; typeface = Typeface.DEFAULT_BOLD }

fun DrawScope.drawBed(m: BedMapper, showGrid: Boolean = true) {
    val w = Bed.WIDTH; val h = Bed.HEIGHT; val s = Bed.SAFE
    val topLeft = Offset(m.x(0.0), min(m.y(0.0), m.y(h)))
    drawRect(Color(0xFF0F151C), topLeft, Size((w * m.scale).toFloat(), (h * m.scale).toFloat()))
    if (showGrid) {
        var v = 0.0
        while (v <= maxOf(w, h)) {
            val major = (v.toInt() % 50) == 0
            val c = if (major) Color(0x2B788CA5) else Color(0x12788CA5)
            if (v <= w) drawLine(c, m.at(Pt(v, 0.0)), m.at(Pt(v, h)), 1f)
            if (v <= h) drawLine(c, m.at(Pt(0.0, v)), m.at(Pt(w, v)), 1f)
            v += if (m.scale * 10 < 6) 50.0 else 10.0
        }
    }
    // L-shaped home band: X < 30 and Y < 30 stay free.
    val band = Color(0x12F2B45C)
    fun rect(x0: Double, y0: Double, x1: Double, y1: Double) {
        val a = m.at(Pt(x0, y0)); val b = m.at(Pt(x1, y1))
        drawRect(band, Offset(min(a.x, b.x), min(a.y, b.y)), Size(kotlin.math.abs(b.x - a.x), kotlin.math.abs(b.y - a.y)))
    }
    rect(0.0, 0.0, w, s); rect(0.0, s, s, h)
    val dash = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))
    drawLine(Color(0x59F2B45C), m.at(Pt(s, h)), m.at(Pt(s, s)), 1.5f, pathEffect = dash)
    drawLine(Color(0x59F2B45C), m.at(Pt(s, s)), m.at(Pt(w, s)), 1.5f, pathEffect = dash)
    drawRect(Color(0x33788CA5), topLeft, Size((w * m.scale).toFloat(), (h * m.scale).toFloat()), style = Stroke(1.5f))
    // origin marker
    val o = m.at(Pt(0.0, 0.0))
    drawCircle(Lc.warn, 6f, o)
    labelPaint.color = Lc.warn.copy(alpha = .8f).toArgb()
    drawContext.canvas.nativeCanvas.drawText("X0/Y0 · Park", o.x + 12f, if (m.originBottom) o.y - 10f else o.y + 32f, labelPaint)
}
