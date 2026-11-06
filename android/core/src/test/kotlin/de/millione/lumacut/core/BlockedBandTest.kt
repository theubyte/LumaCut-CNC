package de.millione.lumacut.core

import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** The Pi blocks the top strip over the whole width (op=work_band): it reports that as a park corner as wide as the travel. */
class BlockedBandTest {
    @BeforeTest fun on() = Bed.configure(370.0, 360.0, 370.0, 35.0)
    @AfterTest fun off() = Bed.configure(370.0, 360.0, 78.0, 35.0)

    private fun poly(vararg p: Pair<Double, Double>) = p.map { Pt(it.first, it.second) }
    private fun unit(w: Double, h: Double) = ImportUnit(listOf(ImportItem(
        listOf(poly(0.0 to 0.0, w to 0.0, w to h, 0.0 to h, 0.0 to 0.0)), null, false, emptyList(), null)), emptyList())

    @Test fun `the whole top strip is blocked, right to left`() {
        assertTrue(Work.bandBlocked)
        assertEquals(Box(0.0, 0.0, 370.0, 35.0), Work.park)
        for (x in listOf(5.0, 180.0, 350.0))
            assertTrue(Element(layerId = "l", kind = "x", paths = listOf(poly(x to 10.0, x + 5 to 10.0))).touchesPark(), "x=$x")
        assertFalse(Element(layerId = "l", kind = "x", paths = listOf(poly(5.0 to 36.0, 300.0 to 36.0))).touchesPark())
    }

    @Test fun `a job in the strip is refused, below it is fine`() {
        val layers = Document.defaultLayers()
        val line = layers.first { it.mode == LayerMode.LINE }
        val top = Element(layerId = line.id, kind = "Linie", paths = listOf(poly(10.0 to 10.0, 50.0 to 10.0)))
        assertFailsWith<JobBuildException> { MarlinWriter().write(Document(layers = layers, elements = listOf(top))) }
        val below = top.copy(transform = Transform(0.0, 30.0))
        assertNotNull(MarlinWriter().write(Document(layers = layers, elements = listOf(below))))
    }

    @Test fun `the middle and the height follow what can be lasered`() {
        assertEquals(325.0, Work.usableHeight)
        assertEquals(Pt(185.0, 197.5), Work.center)
    }

    @Test fun `imports start below the strip`() {
        val units = List(12) { unit(80.0, 30.0) }
        val offsets = ImportLayout.shelf(units.map { it.box }, Work.WIDTH, Work.HEIGHT)
        offsets.forEachIndexed { i, o ->
            assertNotNull(o, "Teil $i")
            val b = units[i].box
            assertFalse(Work.touchesPark(Box(b.minX + o.x, b.minY + o.y, b.maxX + o.x, b.maxY + o.y)), "Teil $i")
        }
    }

    @Test fun `a motif that fits below the strip is moved under it`() {
        val layout = ImportLayout.arrange(listOf(unit(300.0, 320.0)))
        val o = layout.offsets.single()!!
        val b = layout.units.single().box
        val placed = Box(b.minX + o.x, b.minY + o.y, b.maxX + o.x, b.maxY + o.y)
        assertTrue(Work.contains(placed))
        assertFalse(Work.touchesPark(placed))
    }

    @Test fun `a motif too tall for the area is shrunk to it`() {
        val k = ImportLayout.shrinkFactor(listOf(unit(100.0, 400.0)))
        assertEquals((325.0 - 10) / 400.0, k, 1e-9)
    }
}
