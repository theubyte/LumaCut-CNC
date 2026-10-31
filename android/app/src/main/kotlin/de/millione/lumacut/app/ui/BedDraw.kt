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
import androidx.compose.ui.unit.dp
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

/** The work area as a sheet with a 10/50 mm grid, lifted off the dotted background. Nothing outside it is usable. */
fun DrawScope.drawWorkArea(m: WorkMapper, showGrid: Boolean = true) {
    val w = Work.WIDTH; val h = Work.HEIGHT
    val topLeft = m.at(Pt(0.0, 0.0))
    val size = Size((w * m.scale).toFloat(), (h * m.scale).toFloat())
    // Soft shadow under the sheet (light theme), a few widening translucent rims.
    if (!Lc.dark) for (i in 1..4) {
        val g = i * 3f
        drawRect(Lc.shadow.copy(alpha = .05f), topLeft + Offset(-g / 2, g / 2), Size(size.width + g, size.height + g))
    }
    drawRect(Lc.sheet, topLeft, size)
    if (showGrid) {
        val step = if (m.scale * 10 < 6) 50.0 else 10.0
        var v = 0.0
        while (v <= maxOf(w, h)) {
            val c = if ((v.toInt() % 50) == 0) Lc.gridMajor else Lc.grid
            if (v <= w) drawLine(c, m.at(Pt(v, 0.0)), m.at(Pt(v, h)), 1f)
            if (v <= h) drawLine(c, m.at(Pt(0.0, v)), m.at(Pt(w, v)), 1f)
            v += step
        }
    }
    // Park corner (top right): the head homes and parks there, nothing is burnt.
    val park = Work.park
    val pTop = m.at(Pt(park.minX, park.minY)); val pBot = m.at(Pt(park.maxX, park.maxY))
    val pSize = Size(pBot.x - pTop.x, pBot.y - pTop.y)
    drawRect(Lc.warn.copy(alpha = .12f), pTop, pSize)
    var d = 0f
    val hatch = 8.dp.toPx()
    while (d < pSize.width + pSize.height) {
        val a = Offset(pTop.x + minOf(d, pSize.width), pTop.y + maxOf(0f, d - pSize.width))
        val b = Offset(pTop.x + maxOf(0f, d - pSize.height), pTop.y + minOf(d, pSize.height))
        drawLine(Lc.warn.copy(alpha = .45f), a, b, 1f)
        d += hatch
    }
    drawRect(Lc.warn.copy(alpha = .7f), pTop, pSize, style = Stroke(1f))
    drawRect(Lc.line2, topLeft, size, style = Stroke(1.5f))
    // In dp, not pixels: 26 px were huge on an mdpi tablet and tiny on an xxhdpi phone.
    labelPaint.textSize = 12.dp.toPx()
    labelPaint.color = Lc.faint.toArgb()
    drawContext.canvas.nativeCanvas.drawText("0/0", topLeft.x + 6f, topLeft.y + labelPaint.textSize + 4f, labelPaint)
    val dims = "%.0f × %.0f mm".format(w, h)
    drawContext.canvas.nativeCanvas.drawText(dims, topLeft.x + size.width - labelPaint.measureText(dims) - 8f, topLeft.y + size.height - 10f, labelPaint)
}

/** Head marker from a machine position; outside the work area (parked) it sits on the edge, hollow. */
fun DrawScope.drawHead(m: WorkMapper, machinePos: List<Double>?) {
    if (machinePos == null || machinePos.size < 2) return
    val p = Work.fromMachine(machinePos[0], machinePos[1])
    val inside = Work.contains(p)
    val c = m.at(Pt(p.x.coerceIn(0.0, Work.WIDTH), p.y.coerceIn(0.0, Work.HEIGHT)))
    // Laser head: accent ring with a white core; hollow on the edge while parked.
    if (inside) drawCircle(Lc.accent.copy(alpha = .18f), 18f, c)
    if (inside) drawCircle(Color.White, 8f, c)
    drawCircle(Lc.accent, 8f, c, style = Stroke(3f))
}
