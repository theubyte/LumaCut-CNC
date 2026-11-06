package de.millione.lumacut.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertSame
import kotlin.test.assertTrue

class LayerTidyTest {
    private val imported = Layer(name = "Rot", color = 0xFFFF0000)
    private val other = Layer(name = "Blau", color = 0xFF0000FF)
    private val std = Document.defaultLayers()
    private fun element(l: Layer, plate: Int = 0) = Element(layerId = l.id, kind = "x", plate = plate)
    private fun names(d: Document) = d.layers.map { it.name }

    @Test fun `deleting the motif removes its layer, the standard layers stay`() {
        val d = Document(layers = std + imported, elements = listOf(element(imported)))
        assertSame(d, d.withoutEmptyLayers())
        assertEquals(listOf("Gravieren", "Linie", "Schneiden"), names(d.copy(elements = emptyList()).withoutEmptyLayers()))
    }

    @Test fun `content on another plate keeps the layer`() {
        val d = Document(layers = std + imported, elements = listOf(element(imported, plate = 1)), plateCount = 2)
        assertEquals(4, d.withoutEmptyLayers().layers.size)
        assertEquals(listOf("Rot"), names(d.copy(layers = d.shownLayers())))
    }

    @Test fun `a new unused layer survives until it is no longer kept`() {
        val d = Document(layers = std + imported)
        assertEquals(4, d.withoutEmptyLayers(setOf(imported.id)).layers.size)
        assertEquals(listOf("Rot"), d.shownLayers(setOf(imported.id)).map { it.name })
        assertEquals(3, d.withoutEmptyLayers().layers.size)
    }

    @Test fun `a project only with own layers never ends without a layer`() {
        val d = Document(layers = listOf(imported, other))
        assertEquals(listOf("Gravieren", "Linie", "Schneiden"), names(d.withoutEmptyLayers()))
    }

    @Test fun `an empty standard layer is hidden, not removed`() {
        val d = Document(layers = std + imported, elements = listOf(element(std[2]), element(imported)))
        assertEquals(listOf("Schneiden", "Rot"), d.shownLayers().map { it.name })
        assertEquals(4, d.withoutEmptyLayers().layers.size)
    }

    @Test fun `deleting a layer takes its parts on all plates`() {
        val d = Document(layers = std + imported, plateCount = 2,
            elements = listOf(element(imported), element(imported, plate = 1), element(std[0])))
        val r = d.deletingLayer(imported.id)
        assertEquals(3, r.layers.size)
        assertEquals(listOf(std[0].id), r.elements.map { it.layerId })
    }

    @Test fun `deleting a standard layer empties it and keeps it for the tools`() {
        val d = Document(layers = std, elements = listOf(element(std[2]), element(std[0])))
        val r = d.deletingLayer(std[2].id)
        assertEquals(3, r.layers.size)
        assertEquals(listOf(std[0].id), r.elements.map { it.layerId })
    }

    @Test fun `moving jumps over hidden layers`() {
        val d = Document(layers = std + imported)           // Gravieren, Linie, Schneiden, Rot
        val shown = listOf(std[0].id, imported.id)          // Linie and Schneiden are empty and hidden
        assertEquals(listOf("Rot", "Gravieren", "Linie", "Schneiden"), names(d.movingLayer(imported.id, true, shown)))
        assertEquals(listOf("Linie", "Schneiden", "Rot", "Gravieren"), names(d.movingLayer(std[0].id, false, shown)))
    }

    @Test fun `moving at the end of the list changes nothing`() {
        val d = Document(layers = std + imported)
        val shown = listOf(std[0].id, imported.id)
        assertSame(d, d.movingLayer(std[0].id, true, shown))
        assertSame(d, d.movingLayer(imported.id, false, shown))
        assertTrue(d.movingLayer("fehlt", true, shown) === d)
    }
}
