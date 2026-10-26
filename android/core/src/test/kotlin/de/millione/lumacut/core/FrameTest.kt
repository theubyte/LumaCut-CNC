package de.millione.lumacut.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class FrameTest {
    /** Mirrors pi400/marlin/web.py frame_program(): setup lines or absolute laser-off G0 moves. */
    private val piFrameLine = Regex("""^(G21|G90|M5 I|G0 X\d+\.\d{3} Y\d+\.\d{3} F\d+)$""")

    @Test fun `box frame closes around the motif and passes the Pi check`() {
        val g = Frame.program(listOf(Pt(50.0, 60.0), Pt(120.0, 90.0), Pt(80.0, 140.0)), Frame.Mode.BOX)
        val lines = g.trim().lines()
        assertTrue(lines.all { piFrameLine.matches(it) }, g)
        assertEquals("G0 X50.000 Y60.000 F3000", lines[3])
        assertEquals(lines[3], lines.last(), "returns to the start corner")
        assertEquals(3 + 5, lines.size)
    }

    @Test fun `hull drops inner points`() {
        val pts = listOf(Pt(0.0, 0.0), Pt(10.0, 0.0), Pt(10.0, 10.0), Pt(0.0, 10.0), Pt(5.0, 5.0), Pt(2.0, 3.0))
        val hull = Frame.convexHull(pts)
        assertEquals(4, hull.size)
        assertTrue(Pt(5.0, 5.0) !in hull)
    }

    @Test fun `frame from a real toolpath uses only burned points`() {
        val tp = Toolpath.parse("M3 I\nG0 X200 Y200\nG0 X40 Y40\nG1 X60 Y40 S100 F600\nG1 X60 Y70 S100\n")
        val g = Frame.program(Frame.cutPoints(tp), Frame.Mode.BOX)
        assertTrue("X200" !in g)
        assertTrue("G0 X60.000 Y70.000 F3000" in g)
    }
}

class MaterialTestTest {
    private fun fakeLabel(t: String, h: Double): List<Poly> = listOf(listOf(Pt(0.0, 0.0), Pt(t.length * h * .6, h)))

    @Test fun `grid has one layer per cell with its power and speed`() {
        val doc = MaterialTest.build(MaterialTest.Spec(powerSteps = 3, speedSteps = 2, powerFrom = 20.0, powerTo = 60.0,
                                                      speedFrom = 500.0, speedTo = 1500.0), ::fakeLabel)
        assertEquals(1 + 6, doc.layers.size)
        assertEquals(listOf(20.0, 40.0, 60.0), doc.layers.drop(1).take(3).map { it.powerPct })
        assertEquals(listOf(500.0, 1500.0), doc.layers.drop(1).map { it.speed }.distinct())
        assertEquals(6, doc.elements.count { it.kind == "Testfeld" })
        assertEquals(5, doc.elements.count { it.kind == "Beschriftung" })
        val b = doc.bounds()!!
        assertTrue(b.minX >= Bed.SAFE && b.minY >= Bed.SAFE)
    }

    @Test fun `test document produces Pi compatible G-code`() {
        val doc = MaterialTest.build(MaterialTest.Spec(powerSteps = 2, speedSteps = 2, intervalMm = 1.0), ::fakeLabel)
        val g = MarlinWriter().write(doc)
        val t = Toolpath.parse(g)
        assertTrue(t.stats.warnings.isEmpty(), t.stats.warnings.toString())
        assertEquals(1, g.lines().count { it == "M3 I" })
        val powers = g.lines().mapNotNull { Regex("""S(\d+)$""").find(it)?.groupValues?.get(1)?.toInt() }.filter { it > 0 }.toSet()
        assertTrue(powers.containsAll(setOf(51, 255)), powers.toString())   // 20 % and 100 %
    }
}
