package de.millione.lumacut.app.ui

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Work
import kotlin.math.min

/**
 * Maps work-area millimetres (0..360 × 0..340, origin top-left, Y down) to
 * screen pixels. The 30 mm safezone belongs to the laser and is never
 * shown; machine positions are converted with [machine].
 */
class WorkMapper(val scale: Float, val ox: Float, val oy: Float) {
    fun x(mm: Double): Float = ox + mm.toFloat() * scale
    fun y(mm: Double): Float = oy + mm.toFloat() * scale
    fun at(p: Pt) = Offset(x(p.x), y(p.y))
    fun at(xMm: Float, yMm: Float) = Offset(ox + xMm * scale, oy + yMm * scale)
    /** Screen position of a machine coordinate (G-code, head position). */
    fun machine(xMm: Double, yMm: Double) = at(Work.fromMachine(xMm, yMm))
    fun machine(xMm: Float, yMm: Float) = machine(xMm.toDouble(), yMm.toDouble())
    fun toWork(o: Offset) = Pt(((o.x - ox) / scale).toDouble(), ((o.y - oy) / scale).toDouble())
    fun mm(px: Float) = px / scale

    companion object {
        fun fit(size: Size, padding: Float = 24f, zoom: Float = 1f, pan: Offset = Offset.Zero): WorkMapper {
            val base = min((size.width - 2 * padding) / Work.WIDTH.toFloat(), (size.height - 2 * padding) / Work.HEIGHT.toFloat())
            val k = base * zoom
            val ox = (size.width - Work.WIDTH.toFloat() * k) / 2 + pan.x
            val oy = (size.height - Work.HEIGHT.toFloat() * k) / 2 + pan.y
            return WorkMapper(k, ox, oy)
        }
    }
}

private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 26f; typeface = Typeface.DEFAULT_BOLD }

/** The work area with a 10/50 mm grid. Nothing outside it is usable. */
fun DrawScope.drawWorkArea(m: WorkMapper, showGrid: Boolean = true) {
    val w = Work.WIDTH; val h = Work.HEIGHT
    val topLeft = m.at(Pt(0.0, 0.0))
    val size = Size((w * m.scale).toFloat(), (h * m.scale).toFloat())
    drawRect(Color(0xFF0F151C), topLeft, size)
    if (showGrid) {
        val step = if (m.scale * 10 < 6) 50.0 else 10.0
        var v = 0.0
        while (v <= maxOf(w, h)) {
            val major = (v.toInt() % 50) == 0
            val c = if (major) Color(0x2B788CA5) else Color(0x12788CA5)
            if (v <= w) drawLine(c, m.at(Pt(v, 0.0)), m.at(Pt(v, h)), 1f)
            if (v <= h) drawLine(c, m.at(Pt(0.0, v)), m.at(Pt(w, v)), 1f)
            v += step
        }
    }
    drawRect(Color(0x55788CA5), topLeft, size, style = Stroke(1.5f))
    labelPaint.color = Lc.faint.toArgb()
    drawContext.canvas.nativeCanvas.drawText("0/0", topLeft.x + 6f, topLeft.y + 26f, labelPaint)
    drawContext.canvas.nativeCanvas.drawText("%.0f × %.0f mm".format(w, h), topLeft.x + size.width - 170f, topLeft.y + size.height - 10f, labelPaint)
}

/** Head marker from a machine position; outside the work area (parked) it sits on the edge, hollow. */
fun DrawScope.drawHead(m: WorkMapper, machinePos: List<Double>?) {
    if (machinePos == null || machinePos.size < 2) return
    val p = Work.fromMachine(machinePos[0], machinePos[1])
    val inside = Work.contains(p)
    val c = m.at(Pt(p.x.coerceIn(0.0, Work.WIDTH), p.y.coerceIn(0.0, Work.HEIGHT)))
    if (inside) drawCircle(Color.White, 8f, c)
    drawCircle(if (inside) Lc.bg else Color.White, 8f, c, style = Stroke(3f))
}
