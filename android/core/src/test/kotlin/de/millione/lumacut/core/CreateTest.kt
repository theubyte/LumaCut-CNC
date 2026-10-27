package de.millione.lumacut.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class CreateTest {
    /** Stand-in for rendered text: one box per letter, 7 mm high, 6 mm wide, 1 mm apart. */
    private fun fakeText(letters: Int, x: Double = 0.0, y: Double = 0.0) =
        (0 until letters).map { i -> Shapes.rect(6.0, 7.0).map { Pt(it.x + x + i * 7.0, it.y + y) } }

    @Test fun `library shapes fill the dragged box and are closed`() {
        for (k in ShapeKind.entries) {
            val p = ShapeLib.make(k, 40.0, 30.0)
            val b = boundsOf(listOf(p))!!
            assertEquals(40.0, b.width, 1e-6, k.name); assertEquals(30.0, b.height, 1e-6, k.name)
            assertTrue(p.isClosed(1e-6), k.name)
        }
    }

    @Test fun `curve passes through the tapped points`() {
        val pts = listOf(Pt(0.0, 0.0), Pt(10.0, 5.0), Pt(20.0, 0.0), Pt(30.0, 5.0))
        val open = Curves.catmullRom(pts, false)
        for (q in pts) assertTrue(open.any { it.dist(q) < 1e-9 })
        assertEquals(pts.first(), open.first()); assertEquals(pts.last(), open.last())
        val closed = Curves.catmullRom(pts, true)
        assertTrue(closed.isClosed()); for (q in pts) assertTrue(closed.any { it.dist(q) < 1e-9 })
    }

    @Test fun `name tags enclose the text, keychain hole lies inside the outline`() {
        val text = fakeText(4, 50.0, 50.0)
        for (style in TagStyle.entries) {
            val t = Personalize.tag(text, style, 4.0)
            val b = t.bounds()!!
            assertEquals(0.0, b.minX, 1e-6); assertEquals(0.0, b.minY, 1e-6)
            val outline = t.cut.maxByOrNull { boundsOf(listOf(it))!!.let { x -> x.width * x.height } }!!
            val ob = boundsOf(listOf(outline))!!
            val tb = boundsOf(t.engrave)!!
            assertTrue(ob.minX < tb.minX && ob.maxX > tb.maxX && ob.minY < tb.minY && ob.maxY > tb.maxY, style.name)
            assertEquals(2, t.cut.size, style.name)                              // outline + hole
            val hole = boundsOf(listOf(t.cut.minByOrNull { boundsOf(listOf(it))!!.width }!!))!!
            assertEquals(4.0, hole.width, 0.05, style.name)
            assertTrue(hole.minX > ob.minX && hole.maxX < ob.maxX && hole.minY > ob.minY && hole.maxY < ob.maxY, style.name)
            // the hole does not touch the text
            assertTrue(hole.maxX < tb.minX || hole.minX > tb.maxX || hole.maxY < tb.minY || hole.minY > tb.maxY, style.name)
        }
        assertEquals(1, Personalize.tag(text, TagStyle.PLATE, null).cut.size)
    }

    @Test fun `emblem keeps all text inside the circle`() {
        val p = Personalize.emblem(fakeText(2), fakeText(12), fakeText(6), 80.0)
        assertEquals(1, p.cut.size)
        val c = Pt(40.0, 40.0)
        for (poly in p.engrave) for (q in poly) assertTrue(q.dist(c) < 37.0, "$q")
        assertTrue(p.engrave.size == 20)
    }

    @Test fun `frames, dashes, ruler and puzzle`() {
        val box = Box(100.0, 100.0, 150.0, 130.0)
        for (st in Personalize.FrameStyle.entries) {
            val f = boundsOf(Personalize.frame(box, st, 5.0))!!
            assertTrue(f.minX <= 95.0 + 1e-6 && f.maxX >= 155.0 - 1e-6 && f.minY <= 95.0 + 1e-6 && f.maxY >= 135.0 - 1e-6, st.name)
        }
        val d = Personalize.dashes(listOf(Pt(0.0, 0.0), Pt(13.0, 0.0)), 4.0, 2.5)
        assertEquals(listOf(4.0, 4.0, 0.0), d.map { it.length() }.let { it + List(3 - it.size) { 0.0 } }.take(2) + 0.0)
        val r = Personalize.ruler(150, 30.0, null)
        assertEquals(151, r.marks.size); assertEquals(16, r.labels.size); assertEquals("15", r.labels.last().second)
        assertEquals(160.0, boundsOf(r.cut)!!.width, 1e-9)
        val pz = Personalize.puzzle(120.0, 90.0, 4, 3)
        assertEquals(1 + 3 + 2, pz.size)
        assertTrue(boundsOf(pz)!!.let { it.minX >= -1e-9 && it.maxX <= 120.0 + 1e-9 })
        assertEquals(pz.map { it.size }, Personalize.puzzle(120.0, 90.0, 4, 3).map { it.size })   // same seed, same puzzle
    }
}
