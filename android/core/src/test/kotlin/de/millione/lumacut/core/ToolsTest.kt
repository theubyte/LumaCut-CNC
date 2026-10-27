package de.millione.lumacut.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ToolsTest {
    private fun sq(x: Double, y: Double, s: Double) = Shapes.rect(s, s).map { Pt(it.x + x, it.y + y) }

    /** Area of a closed polyline (shoelace). */
    private fun area(p: Poly) = abs(p.zipWithNext().sumOf { (a, b) -> a.x * b.y - b.x * a.y }) / 2

    @Test fun `align left and centre, distribute evenly`() {
        val boxes = listOf(Box(10.0, 0.0, 20.0, 10.0), Box(50.0, 5.0, 80.0, 15.0), Box(30.0, 40.0, 35.0, 50.0))
        val ref = boxes.reduce { a, b -> a.union(b) }
        assertEquals(listOf(0.0, -40.0, -20.0), Align.offsets(boxes, Align.Mode.LEFT, ref).map { it.x })
        assertEquals(listOf(0.0, 0.0, 0.0), Align.offsets(boxes, Align.Mode.LEFT, ref).map { it.y })
        assertEquals(listOf(25.0, 20.0, -15.0), Align.offsets(boxes, Align.Mode.BOTTOM, Box(0.0, 0.0, 100.0, 35.0)).map { it.y })
        // widths 10, 30, 5 between 10 and 80: free 25 -> gap 12.5; order by left edge: 10, 30, 50
        val d = Align.distribute(boxes, true)
        assertEquals(0.0, d[0].x, 1e-9); assertEquals(0.0, d[1].x, 1e-9)
        assertEquals(10.0 + 10 + 12.5 - 30.0, d[2].x, 1e-9)
    }

    @Test fun `weld, subtract and intersect two overlapping squares`() {
        val a = listOf(sq(0.0, 0.0, 20.0)); val b = listOf(sq(10.0, 0.0, 20.0))
        val union = Booleans.apply(listOf(a, b), Booleans.Op.UNION)
        assertEquals(1, union.size); assertEquals(600.0, area(union[0]), 12.0)
        val sub = Booleans.apply(listOf(a, b), Booleans.Op.SUBTRACT)
        assertEquals(1, sub.size); assertEquals(200.0, area(sub[0]), 8.0)
        assertTrue(boundsOf(sub)!!.maxX < 10.2)
        val cut = Booleans.apply(listOf(a, b), Booleans.Op.INTERSECT)
        assertEquals(200.0, area(cut[0]), 8.0); assertTrue(boundsOf(cut)!!.minX > 9.8)
        assertTrue(Booleans.apply(listOf(a, listOf(sq(50.0, 0.0, 5.0))), Booleans.Op.INTERSECT).isEmpty())
        // subtracting a small square from the middle leaves a hole: outline + hole
        assertEquals(2, Booleans.apply(listOf(a, listOf(sq(5.0, 5.0, 10.0))), Booleans.Op.SUBTRACT).size)
    }

    @Test fun `tabs leave gaps of the given width`() {
        val square = sq(0.0, 0.0, 40.0)                          // length 160
        val cut = Tabs.apply(listOf(square), 4, 1.0)
        assertEquals(4, cut.size)
        assertEquals(156.0, cut.sumOf { it.length() }, 1e-6)
        assertTrue(cut.none { it.isClosed() })
        for (piece in cut) for (q in piece) assertTrue(square.zipWithNext().any { (a, b) -> abs(Pt(b.x - a.x, b.y - a.y).let { (it.x * (q.y - a.y) - it.y * (q.x - a.x)) }) < 1e-6 })
        val open = listOf(Pt(0.0, 0.0), Pt(10.0, 0.0))
        assertEquals(listOf(open), Tabs.apply(listOf(open), 4, 1.0))       // open paths stay
        assertEquals(listOf(sq(0.0, 0.0, 2.0)), Tabs.apply(listOf(sq(0.0, 0.0, 2.0)), 4, 1.0)) // too small
    }

    @Test fun `nesting spreads over plates, too big stays out`() {
        val boxes = List(5) { Box(0.0, 0.0, 200.0, 200.0) } + Box(0.0, 0.0, 400.0, 10.0) + Box(0.0, 0.0, 50.0, 50.0)
        val placed = Nest.place(boxes)
        assertNull(placed[5])
        assertEquals(5, placed.filterNotNull().map { it.first }.distinct().size)
        for ((i, pl) in placed.withIndex()) pl?.let { (_, o) ->
            val b = boxes[i]; assertTrue(Work.contains(Box(b.minX + o.x, b.minY + o.y, b.maxX + o.x, b.maxY + o.y)))
        }
        assertNotNull(placed[6])
    }

    @Test fun `box panels mate and keep their outer size`() {
        val s = BoxSpec(w = 100.0, d = 60.0, h = 50.0, t = 3.0, finger = 10.0)
        val panels = BoxMaker.panels(s).toMap()
        assertEquals(setOf("Boden", "Vorne", "Hinten", "Links", "Rechts"), panels.keys)
        val bottom = boundsOf(listOf(panels.getValue("Boden")))!!
        assertEquals(100.0, bottom.width, 1e-9); assertEquals(60.0, bottom.height, 1e-9)
        val front = boundsOf(listOf(panels.getValue("Vorne")))!!
        assertEquals(100.0, front.width, 1e-9); assertEquals(50.0, front.height, 1e-9)
        val side = boundsOf(listOf(panels.getValue("Links")))!!
        assertEquals(60.0, side.width, 1e-9)                        // fingers in the middle reach the outline
        assertTrue(panels.values.all { it.isClosed() })
        assertEquals(9, BoxMaker.segments(100.0, 10.0)); assertEquals(5, BoxMaker.segments(50.0, 10.0)); assertEquals(1, BoxMaker.segments(15.0, 10.0))
        // front: 5 of 9 notches on the bottom edge, 2 of 5 on each side; side: 3 of 5 on three edges, two corners notched twice
        assertEquals(5000.0 - 5 * 100.0 / 9 * 3 - 4 * 10.0 * 3, area(panels.getValue("Vorne")), 1e-6)
        assertEquals(3000.0 - 3 * 10.0 * 3 * 2 - 3 * 12.0 * 3 + 2 * 9.0, area(panels.getValue("Links")), 1e-6)
        assertEquals(6, BoxMaker.panels(s.copy(closed = true)).size)
    }
}
