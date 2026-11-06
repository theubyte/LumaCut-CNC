package de.millione.lumacut.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class ParkCornerTest {
    private fun poly(vararg p: Pair<Double, Double>) = p.map { Pt(it.first, it.second) }
    private fun el(vararg polys: List<Pt>) = Element(layerId = "l", kind = "x", paths = polys.toList())
    private val w get() = Work.WIDTH

    @Test fun `the area is the measured one, the label follows it`() {
        assertEquals("370 × 360 mm", Work.sizeLabel)
        assertEquals(Box(292.0, 0.0, 370.0, 35.0), Work.park)
        assertEquals(Pt(0.0, 0.0), Work.toMachine(Pt(w, 0.0)))     // top right on screen = machine 0/0
    }

    @Test fun `a line through the corner touches it, one beside it does not`() {
        assertTrue(el(poly(w - 40 to 10.0, w - 10 to 10.0)).touchesPark())
        assertTrue(el(poly(200.0 to 10.0, w - 10 to 10.0)).touchesPark())
        assertFalse(el(poly(100.0 to 10.0, 290.0 to 10.0)).touchesPark())
        assertFalse(el(poly(w - 40 to 40.0, w - 10 to 40.0)).touchesPark())
    }

    @Test fun `parts far apart in one element are no reason to refuse it`() {
        val left = poly(10.0 to 10.0, 20.0 to 10.0)
        val below = poly(w - 20 to 200.0, w - 10 to 200.0)
        val e = el(left, below)
        assertTrue(Work.touchesPark(e.worldBounds()!!), "its box reaches the corner")
        assertFalse(e.touchesPark())
    }

    @Test fun `a closed shape around the corner counts, a picture over it too`() {
        val around = poly(250.0 to -5.0, 365.0 to -5.0, 365.0 to 34.0, 250.0 to 34.0, 250.0 to -5.0)
        assertTrue(el(around).touchesPark())
        val big = poly(200.0 to 1.0, 369.0 to 1.0, 369.0 to 100.0, 200.0 to 100.0, 200.0 to 1.0)
        assertTrue(el(big).touchesPark())
        val image = Element(layerId = "l", kind = "Bild", transform = Transform(w - 30, 5.0), imageWidthMm = 10.0, imageHeightMm = 10.0,
            raster = Raster.of(1, 1, byteArrayOf(0)))
        assertTrue(image.touchesPark())
    }

    @Test fun `the job check looks at burning lines like the Pi`() {
        fun warnings(g: String) = Toolpath.parse(g).stats.warnings
        val apart = "G21\nG90\nM3 I\nG0 X300 Y5\nG1 X310 Y5 F1000 S100\nG0 X10 Y300\nG1 X20 Y300 F1000 S100\nM5 I\n"
        assertTrue(warnings(apart).none { "Park" in it }, "the bounding box of the job reaches the corner, no line does")
        val through = "G21\nG90\nM3 I\nG0 X10 Y5\nG1 X20 Y5 F1000 S100\nM5 I\n"
        assertNotNull(warnings(through).firstOrNull { "Park" in it })
        val travelOnly = "G21\nG90\nM3 I\nG0 X10 Y5\nG0 X200 Y200\nG1 X210 Y200 F1000 S100\nM5 I\n"
        assertTrue(warnings(travelOnly).none { "Park" in it })
    }

    private fun unit(wMm: Double, hMm: Double): ImportUnit = ImportUnit(listOf(ImportItem(
        listOf(poly(0.0 to 0.0, wMm to 0.0, wMm to hMm, 0.0 to hMm, 0.0 to 0.0)), null, false, emptyList(), null)), emptyList())

    @Test fun `packed parts stay out of the corner`() {
        val units = List(30) { unit(60.0, 30.0) }
        val offsets = ImportLayout.shelf(units.map { it.box }, Work.WIDTH, Work.HEIGHT)
        offsets.forEachIndexed { i, o ->
            assertNotNull(o, "Teil $i")
            val b = units[i].box
            assertFalse(Work.touchesPark(Box(b.minX + o.x, b.minY + o.y, b.maxX + o.x, b.maxY + o.y)), "Teil $i in der Park-Ecke")
        }
    }

    @Test fun `a part wider than the top row starts below the corner`() {
        val u = unit(320.0, 20.0)
        val o = ImportLayout.shelf(listOf(u.box), Work.WIDTH, Work.HEIGHT).single()
        assertNotNull(o)
        assertTrue(o.y >= Bed.PARK_Y)
    }

    @Test fun `a big motif centred into the corner is moved clear`() {
        val layout = ImportLayout.arrange(listOf(unit(230.0, 300.0)))
        assertEquals(FitKind.AS_IS, layout.kind)
        val o = layout.offsets.single()!!
        val b = layout.units.single().box
        val placed = Box(b.minX + o.x, b.minY + o.y, b.maxX + o.x, b.maxY + o.y)
        assertTrue(Work.contains(placed))
        assertFalse(Work.touchesPark(placed))
    }

    @Test fun `a motif that fits centred stays centred`() {
        val o = ImportLayout.arrange(listOf(unit(100.0, 100.0))).offsets.single()!!
        assertEquals(Pt(Work.WIDTH / 2 - 50, Work.HEIGHT / 2 - 50), o)
    }
}
