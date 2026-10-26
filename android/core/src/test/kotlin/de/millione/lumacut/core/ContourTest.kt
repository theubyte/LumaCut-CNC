package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ContourTest {
    private val p = 6.0

    private fun mask(widthMm: Double, heightMm: Double, inside: (Double, Double) -> Boolean): Mask {
        val w = (widthMm * p).toInt(); val h = (heightMm * p).toInt()
        return Mask(w, h, BooleanArray(w * h) { inside(((it % w) + 0.5) / p, ((it / w) + 0.5) / p) }, p)
    }

    private fun area(poly: Poly): Double = abs(poly.zipWithNext().sumOf { (a, b) -> a.x * b.y - b.x * a.y }) / 2

    private fun selfIntersects(poly: Poly): Boolean {
        fun cross(o: Pt, a: Pt, b: Pt) = (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
        val n = poly.size - 1
        for (i in 0 until n) for (j in i + 2 until n) {
            if (i == 0 && j == n - 1) continue
            val a = poly[i]; val b = poly[i + 1]; val c = poly[j]; val d = poly[j + 1]
            if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) return true
        }
        return false
    }

    private val circle = mask(60.0, 60.0) { x, y -> hypot(x - 30, y - 30) <= 10 }
    private val square = mask(60.0, 60.0) { x, y -> x in 20.0..40.0 && y in 20.0..40.0 }

    @Test fun `edge of a circle has the right size and is a closed simple line`() {
        val loops = Contour.edge(circle)
        assertEquals(1, loops.size)
        val b = boundsOf(loops)!!
        assertEquals(20.0, b.width, 0.2); assertEquals(20.0, b.height, 0.2)
        assertEquals(30.0, b.center.x, 0.1); assertEquals(30.0, b.center.y, 0.1)
        assertTrue(loops[0].isClosed()); assertTrue(!selfIntersects(loops[0]))
        assertEquals(PI * 100, area(loops[0]), PI * 100 * 0.02)
        // vertices are simplified, not one per pixel
        assertTrue(loops[0].size < 400, "size ${loops[0].size}")
    }

    @Test fun `inset moves the line inwards and sticker outwards by the given distance`() {
        val inner = Contour.edge(circle, insetMm = 0.5)
        assertEquals(19.0, boundsOf(inner)!!.width, 0.2)
        val sticker = Contour.sticker(circle, 3.0)
        assertEquals(1, sticker.size)
        assertEquals(26.0, boundsOf(sticker)!!.width, 0.25)
        assertTrue(!selfIntersects(sticker[0]))
    }

    @Test fun `sticker around a square has rounded corners`() {
        val loops = Contour.sticker(square, 3.0)
        assertEquals(1, loops.size)
        val b = boundsOf(loops)!!
        assertEquals(26.0, b.width, 0.25); assertEquals(26.0, b.height, 0.25)
        val expected = 400.0 + 4 * 20 * 3 + PI * 9          // square + 4 strips + 4 quarter circles
        assertEquals(expected, area(loops[0]), expected * 0.02)
        // the corner of the bounding box is cut: no vertex lies near (17,17)
        assertTrue(loops[0].none { it.x < 17.6 && it.y < 17.6 }, "corner must be round")
        assertTrue(!selfIntersects(loops[0]))
    }

    @Test fun `only the outer contour, holes are ignored`() {
        val ring = mask(60.0, 60.0) { x, y -> hypot(x - 30, y - 30).let { it <= 15 && it >= 8 } }
        val loops = Contour.edge(ring)
        assertEquals(1, loops.size)
        assertEquals(30.0, boundsOf(loops)!!.width, 0.2)
    }

    @Test fun `separate parts give one contour each, close parts and gaps merge in a sticker`() {
        val two = mask(100.0, 40.0) { x, y -> y in 10.0..30.0 && (x in 10.0..30.0 || x in 70.0..90.0) }
        assertEquals(2, Contour.edge(two).size)
        assertEquals(2, Contour.sticker(two, 3.0).size)
        val near = mask(60.0, 40.0) { x, y -> y in 10.0..30.0 && (x in 10.0..28.0 || x in 31.0..50.0) }   // 3 mm gap
        assertEquals(2, Contour.edge(near).size)
        val merged = Contour.sticker(near, 1.0)
        assertEquals(1, merged.size, "gap smaller than the closing distance is closed")
        assertTrue(!selfIntersects(merged[0]))
        val apart = mask(80.0, 40.0) { x, y -> y in 10.0..30.0 && (x in 10.0..30.0 || x in 42.0..62.0) }   // 12 mm gap
        assertEquals(2, Contour.sticker(apart, 3.0).size)
        assertEquals(1, Contour.sticker(apart, 3.0, join = true).size, "join connects distant parts")
    }

    @Test fun `specks are dropped`() {
        val withSpeck = mask(60.0, 60.0) { x, y -> hypot(x - 30, y - 30) <= 10 || hypot(x - 5, y - 5) <= 0.4 }
        assertEquals(1, Contour.edge(withSpeck).size)
    }

    @Test fun `background is found from the picture edge, holes stay part of the motif`() {
        val w = 80; val h = 80
        val white = 0xFFFFFFFF.toInt(); val dark = 0xFF202020.toInt()
        // dark disc on white with a white hole inside
        val px = IntArray(w * h) { val x = it % w - 40; val y = it / w - 40; val d = hypot(x.toDouble(), y.toDouble()); if (d <= 25 && d >= 8) dark else white }
        val m = Mask.fromArgb(px, w, h, 40.0, 40.0)
        assertEquals(Box(0.0, 0.0, 40.0, 40.0).width, m.w / m.pxPerMm, 1e-6)
        val loops = Contour.edge(m)
        assertEquals(1, loops.size)
        assertEquals(25.5, boundsOf(loops)!!.width, 0.3)             // 51 px at 2 px/mm
        // transparency counts as background as well
        val clear = IntArray(w * h) { val x = it % w - 40; val y = it / w - 40; if (hypot(x.toDouble(), y.toDouble()) <= 20) dark else 0x00000000 }
        assertEquals(20.5, boundsOf(Contour.edge(Mask.fromArgb(clear, w, h, 40.0, 40.0)))!!.width, 0.3)
    }

    @Test fun `vector offset grows and shrinks, holes of letters are kept`() {
        val rect = Shapes.rect(20.0, 10.0)
        val grown = Contour.fromPolys(listOf(rect), 2.0)
        assertEquals(1, grown.size)
        assertEquals(24.0, boundsOf(grown)!!.width, 0.2); assertEquals(14.0, boundsOf(grown)!!.height, 0.2)
        val shrunk = Contour.fromPolys(listOf(rect), -2.0)
        assertEquals(16.0, boundsOf(shrunk)!!.width, 0.2); assertEquals(6.0, boundsOf(shrunk)!!.height, 0.2)
        assertTrue(Contour.fromPolys(listOf(rect), -6.0).isEmpty(), "shrunk to nothing")
        val outer = Shapes.rect(30.0, 30.0)
        val hole = Shapes.rect(10.0, 10.0).map { Pt(it.x + 10, it.y + 10) }
        assertEquals(2, Contour.fromPolys(listOf(outer, hole), 1.0).size, "outline plus inner outline")
        assertEquals(1, Contour.fromPolys(listOf(outer, hole), 1.0, outerOnly = true).size)
    }
}
