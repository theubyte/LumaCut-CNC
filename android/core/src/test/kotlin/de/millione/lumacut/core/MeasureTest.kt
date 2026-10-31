package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class MeasureTest {
    private fun sq(x: Double, y: Double, s: Double): Poly = Shapes.rect(s, s).map { Pt(it.x + x, it.y + y) }
    private val layer = Layer(id = "L", name = "Schneiden", color = 0xFFFF0000, mode = LayerMode.LINE, passes = 2)
    private fun el(id: String, paths: List<Poly>, t: Transform = Transform(), kind: String = "Form") =
        Element(id = id, layerId = "L", kind = kind, transform = t, paths = paths)
    private fun doc(vararg e: Element) = Document(layers = listOf(layer), elements = e.toList())

    @Test fun `square has perimeter 40 and area 100`() {
        val s = listOf(sq(0.0, 0.0, 10.0))
        assertEquals(40.0, Measure.perimeter(s), 1e-9)
        assertEquals(100.0, Measure.area(s), 1e-9)
    }

    @Test fun `hole is subtracted and an island inside the hole is added back`() {
        val outer = sq(0.0, 0.0, 20.0); val hole = sq(5.0, 5.0, 10.0); val island = sq(8.0, 8.0, 4.0)
        assertEquals(400.0 - 100.0, Measure.area(listOf(outer, hole)), 1e-9)
        assertEquals(400.0 - 100.0 + 16.0, Measure.area(listOf(outer, hole, island)), 1e-9)
        assertEquals(0.0, Measure.area(listOf(listOf(Pt(0.0, 0.0), Pt(10.0, 0.0)))), 1e-9)
    }

    @Test fun `circle perimeter and area follow pi within polygon tolerance`() {
        val c = listOf(Shapes.ellipse(20.0, 20.0))
        assertEquals(2 * PI * 10, Measure.perimeter(c), 2 * PI * 10 * 0.005)
        assertEquals(PI * 100, Measure.area(c), PI * 100 * 0.005)
        assertNotNull(Measure.ellipseAxes(c))
        assertNull(Measure.ellipseAxes(listOf(sq(0.0, 0.0, 10.0))))
    }

    @Test fun `parallel lines are 5 apart and crossing lines are 0`() {
        val a = listOf(listOf(Pt(0.0, 0.0), Pt(10.0, 0.0)))
        val b = listOf(listOf(Pt(2.0, 5.0), Pt(12.0, 5.0)))
        val h = Measure.polyDistance(a, b)!!
        assertEquals(5.0, h.distance, 1e-9); assertTrue(h.parallel)
        val x = listOf(listOf(Pt(5.0, -3.0), Pt(5.0, 3.0)))
        val c = Measure.polyDistance(a, x)!!
        assertEquals(0.0, c.distance, 1e-12); assertTrue(!c.parallel)
        val far = Measure.polyDistance(a, listOf(listOf(Pt(13.0, 4.0), Pt(20.0, 4.0))))!!
        assertEquals(5.0, far.distance, 1e-9)      // 3 across, 4 up from the end point (10, 0)
    }

    @Test fun `distance of two squares`() {
        val h = Measure.polyDistance(listOf(sq(0.0, 0.0, 10.0)), listOf(sq(14.0, 0.0, 10.0)))!!
        assertEquals(4.0, h.distance, 1e-9)
    }

    @Test fun `angle between rays`() {
        assertEquals(90.0, Measure.angleDeg(Pt(1.0, 0.0), Pt(0.0, 0.0), Pt(0.0, 1.0)), 1e-9)
        assertEquals(180.0, Measure.angleDeg(Pt(-1.0, 0.0), Pt(0.0, 0.0), Pt(1.0, 0.0)), 1e-9)
        assertEquals(45.0, Measure.angleDeg(Pt(1.0, 0.0), Pt(0.0, 0.0), Pt(1.0, 1.0)), 1e-9)
        assertEquals(45.0, Measure.lineAngleDeg(Pt(0.0, 10.0), Pt(10.0, 0.0)), 1e-9)   // up to the right on screen
    }

    @Test fun `snap prefers corner over midpoint over edge`() {
        val e = el("s", listOf(Shapes.rect(10.0, 10.0)), Transform(100.0, 100.0))
        val els = listOf(e)
        val corner = Snap.find(Pt(100.5, 100.2), 2.0, els, workArea = false)!!
        assertEquals(SnapKind.CORNER, corner.kind); assertEquals(100.0, corner.p.x, 1e-9); assertEquals(100.0, corner.p.y, 1e-9)
        val mid = Snap.find(Pt(105.0, 100.3), 1.0, els, workArea = false)!!
        assertEquals(SnapKind.MID, mid.kind); assertEquals(105.0, mid.p.x, 1e-9)
        val edge = Snap.find(Pt(103.0, 100.2), 1.0, els, workArea = false)!!
        assertEquals(SnapKind.EDGE, edge.kind); assertEquals(103.0, edge.p.x, 1e-9); assertEquals(100.0, edge.p.y, 1e-9)
        val center = Snap.find(Pt(105.4, 104.8), 1.0, els, workArea = false)!!
        assertEquals(SnapKind.CENTER, center.kind); assertEquals(105.0, center.p.x, 1e-9)
        assertNull(Snap.find(Pt(150.0, 150.0), 2.0, els, workArea = false))
    }

    @Test fun `circle snaps to its centre and to edge points, not to every segment`() {
        val e = el("c", listOf(Shapes.ellipse(20.0, 20.0)), Transform(50.0, 50.0), "Ellipse")
        val c = Snap.find(Pt(60.2, 59.9), 2.0, listOf(e), workArea = false)!!
        assertEquals(SnapKind.CENTER, c.kind); assertEquals(60.0, c.p.x, 0.01)
        val onRim = Snap.find(Pt(70.3, 60.0), 1.0, listOf(e), workArea = false)!!
        assertEquals(SnapKind.EDGE, onRim.kind)
    }

    @Test fun `work area corners and centre are caught`() {
        assertEquals(SnapKind.CORNER, Snap.find(Pt(1.0, 1.5), 3.0, emptyList())!!.kind)
        val c = Snap.find(Pt(186.0, 180.5), 3.0, emptyList())!!
        assertEquals(SnapKind.CENTER, c.kind); assertEquals(185.0, c.p.x, 1e-9); assertEquals(180.0, c.p.y, 1e-9)
    }

    @Test fun `image corners are caught`() {
        val img = Element(id = "i", layerId = "L", kind = "Bild", raster = Raster.of(2, 2, ByteArray(4)), imageWidthMm = 30.0, imageHeightMm = 20.0,
            transform = Transform(10.0, 10.0))
        val h = Snap.find(Pt(39.5, 30.4), 2.0, listOf(img), workArea = false)!!
        assertEquals(SnapKind.CORNER, h.kind); assertEquals(40.0, h.p.x, 1e-9); assertEquals(30.0, h.p.y, 1e-9)
    }

    @Test fun `transform invert round-trips`() {
        val t = Transform(12.0, -4.0, 2.0, 0.5, 37.0)
        val p = Pt(3.0, 7.0)
        val q = t.invert(t.apply(p))
        assertEquals(p.x, q.x, 1e-9); assertEquals(p.y, q.y, 1e-9)
    }

    @Test fun `anchored point follows its element, deleted element marks stale`() {
        val e = el("s", listOf(Shapes.rect(10.0, 10.0)), Transform(100.0, 100.0))
        val d1 = doc(e)
        val pt = MeasPt.of(Snap.find(Pt(110.2, 110.2), 2.0, d1.elements, workArea = false), Pt(0.0, 0.0), d1.elements)
        val m = Measurement.Distance(pt, MeasPt(Pt(120.0, 110.0)))
        val v1 = MeasureEval.eval(m, d1)
        assertEquals("10.00", v1.copy); assertTrue(!v1.stale)
        val d2 = doc(e.copy(transform = Transform(150.0, 100.0)))
        assertEquals("40.00", MeasureEval.eval(m, d2).copy.let { it })       // corner (110,110) moved to (160,110), other at (120,110)
        assertTrue(MeasureEval.eval(m, doc()).stale)
    }

    @Test fun `element info of a square with hole and a circle`() {
        val e = el("a", listOf(sq(0.0, 0.0, 20.0), sq(5.0, 5.0, 10.0)), Transform(10.0, 10.0))
        val v = MeasureEval.eval(Measurement.Info(listOf("a")), doc(e))
        assertTrue(v.lines.any { it == "Fläche 300.00 mm²" }, v.lines.toString())
        assertTrue(v.lines.any { it == "Umfang 120.00 mm" }, v.lines.toString())
        assertTrue(v.lines.any { it.startsWith("Mittelpunkt X 20.00 · Y 20.00") })
        assertTrue(v.lines.any { it == "Laserweg auf „Schneiden“ 240.00 mm (2 Durchgänge)" }, v.lines.toString())
        val c = el("c", listOf(Shapes.ellipse(20.0, 20.0)), Transform(0.0, 0.0), "Ellipse")
        val cv = MeasureEval.eval(Measurement.Info(listOf("c")), doc(c))
        assertTrue(cv.lines.any { it.startsWith("Kreis Ø 20.00 mm") }, cv.lines.toString())
        val g = MeasureEval.eval(Measurement.Info(listOf("a", "c")), doc(e, c))
        assertTrue(g.title.startsWith("Gruppe"))
    }

    @Test fun `gap between two elements and edges to the work area`() {
        val a = el("a", listOf(Shapes.rect(10.0, 10.0)), Transform(0.0, 0.0))
        val b = el("b", listOf(Shapes.rect(10.0, 10.0)), Transform(15.0, 0.0))
        val g = MeasureEval.eval(Measurement.Gap("a", "b"), doc(a, b))
        assertEquals("5.00", g.copy); assertTrue(g.lines.any { it.startsWith("parallel") })
        val c = el("c", listOf(Shapes.rect(10.0, 10.0)), Transform(5.0, 5.0))
        assertEquals("0.00", MeasureEval.eval(Measurement.Gap("a", "c"), doc(a, c)).copy)
        val r = MeasureEval.eval(Measurement.Edges(listOf("b")), doc(b))
        assertEquals(listOf("Links 15.00 mm", "Rechts 345.00 mm", "Oben 0.00 mm", "Unten 350.00 mm"), r.lines)
    }

    @Test fun `pick takes the nearest outline, else the shape under the finger`() {
        val a = el("a", listOf(Shapes.rect(10.0, 10.0)), Transform(0.0, 0.0))
        val b = el("b", listOf(Shapes.rect(10.0, 10.0)), Transform(50.0, 0.0))
        assertEquals("b", Snap.pick(Pt(49.0, 5.0), 2.0, listOf(a, b))!!.id)
        assertEquals("a", Snap.pick(Pt(5.0, 5.0), 2.0, listOf(a, b))!!.id)      // inside, outline far away
        assertNull(Snap.pick(Pt(30.0, 5.0), 2.0, listOf(a, b)))
    }
}
