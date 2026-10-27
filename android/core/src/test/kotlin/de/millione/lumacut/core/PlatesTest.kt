package de.millione.lumacut.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class PlatesTest {
    private val layers = Document.defaultLayers()
    private fun el(id: String, plate: Int) = Element(id = id, layerId = layers[1].id, kind = "Rechteck", paths = listOf(Shapes.rect(10.0, 10.0)), plate = plate)

    private val doc = Document(layers = layers, elements = listOf(el("a", 0), el("b", 1), el("c", 1), el("d", 2)), plateCount = 3, activePlate = 1)

    @Test fun `plate view holds only that plate`() {
        assertEquals(listOf("b", "c"), doc.plateView().elements.map { it.id })
        assertEquals(listOf("a"), doc.plateView(0).elements.map { it.id })
        assertEquals(listOf(1, 2, 1), (0..2).map(doc::plateSize))
    }

    @Test fun `edits of the view go back onto the active plate, others untouched`() {
        val view = doc.plateView()
        val edited = view.copy(title = "Neu", elements = view.elements.filter { it.id != "b" } + el("e", 0))
        val out = doc.withPlate(edited)
        assertEquals("Neu", out.title)
        assertEquals(setOf("a", "c", "d", "e"), out.elements.map { it.id }.toSet())
        assertEquals(1, out.elements.first { it.id == "e" }.plate)          // new elements land on the active plate
        assertEquals(0, out.elements.first { it.id == "a" }.plate)
        assertEquals(2, out.elements.first { it.id == "d" }.plate)
    }

    @Test fun `add, move and remove plates`() {
        val added = doc.addPlate()
        assertEquals(4, added.plateCount); assertEquals(3, added.activePlate)
        val moved = doc.moveToPlate(setOf("b"), 2)
        assertEquals(listOf("b", "d"), moved.plateView(2).elements.map { it.id })
        assertEquals(doc, doc.moveToPlate(setOf("b"), 5))                    // no such plate
        val removed = doc.removePlate(1)
        assertEquals(2, removed.plateCount); assertEquals(0, removed.activePlate)
        assertEquals(listOf("a" to 0, "d" to 1), removed.elements.map { it.id to it.plate })
        val single = Document(layers = layers)
        assertEquals(single, single.removePlate(0))                         // the last plate stays
    }

    @Test fun `old project files get one plate, plates survive json`() {
        val old = Document.fromJson("""{"title":"Alt","elements":[{"layerId":"l","kind":"Text"}]}""")
        assertEquals(1, old.plateCount); assertEquals(0, old.elements[0].plate)
        assertEquals(doc, Document.fromJson(doc.toJson()))
        val broken = Document.fromJson(doc.copy(plateCount = 1, activePlate = 7).toJson())
        assertEquals(3, broken.plateCount); assertEquals(2, broken.activePlate)
    }

    @Test fun `marlin output of a plate contains only its elements`() {
        val g0 = MarlinWriter("t").write(doc.plateView(0))
        val g1 = MarlinWriter("t").write(doc.plateView(1))
        assertTrue(g1.length > g0.length)
    }
}

class SpreadTest {
    private fun rect(x: Double, w: Double, h: Double, group: String) =
        ImportItem(listOf(Shapes.rect(w, h).map { Pt(it.x + x, it.y) }), null, false, listOf(group), null)

    @Test fun `parts that do not fit on one plate continue on the next, original size`() {
        // five 200 x 200 parts: one per plate in width (200+5+200 > 358) and height (> 338)
        val items = (0 until 5).map { rect(it * 300.0, 200.0, 200.0, "g$it") } + rect(2000.0, 500.0, 50.0, "big")
        val units = ImportLayout.units(VectorImport(items.flatMap { it.polys }, emptyList(), emptyList(), items))
        val s = ImportLayout.spread(units)
        assertEquals(5, s.plates.size); assertEquals(1, s.leftOut)        // the 500 mm part fits on no plate
        val placedOn = units.indices.map { i -> s.plates.indexOfFirst { it.offsets[i] != null } }
        assertEquals(listOf(0, 1, 2, 3, 4, -1), placedOn.sortedWith(compareBy { if (it < 0) 99 else it }))
        for (l in s.plates) for (i in l.units.indices) l.offsets[i]?.let { o ->
            val b = l.units[i].box
            assertTrue(Work.contains(Box(b.minX + o.x, b.minY + o.y, b.maxX + o.x, b.maxY + o.y)))
            assertEquals(200.0, b.width, 1e-9)                              // never scaled
        }
    }
}
