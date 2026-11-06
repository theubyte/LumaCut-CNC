package de.millione.lumacut.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SvgStructureTest {
    private fun svg(body: String) = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">$body</svg>"""
    private fun parse(body: String) = SvgImport.parseImport(svg(body).toByteArray())
    private val square = """<rect x="10" y="10" width="10" height="10" """
    private val other = """<rect x="40" y="10" width="10" height="10" """

    @Test fun `two colours become layers, stroke is a line and fill is a fill`() {
        val r = parse("""$square stroke="#ff0000" fill="none"/>$other fill="#0000ff"/>""")
        assertEquals(listOf("#ff0000", "#0000ff"), r.items.map { it.layerKey })
        assertEquals(listOf(false, true), r.items.map { it.fill })
        assertEquals(listOf("Rot", "Blau"), r.layers.map { it.name })
    }

    @Test fun `one colour stays on the layer the operator chose`() {
        val r = parse("""$square fill="#000"/>$other fill="black"/>""")
        assertTrue(r.items.all { it.layerKey == null })
        assertTrue(r.layers.isEmpty())
    }

    @Test fun `same colour as line and fill is told apart`() {
        val r = parse("""$square stroke="black" fill="none"/>$other fill="black"/>""")
        assertEquals(listOf(false, true), r.items.map { it.fill })
        assertEquals(setOf("#000000"), r.items.map { it.layerKey }.toSet())
    }

    @Test fun `colours from style attribute, css class and parent group`() {
        val r = parse("""<style>.a{fill:#00ff00} .b,.c{stroke:rgb(255,0,0);fill:none}</style>
            $square class="a"/>$other class="c"/><g fill="#0000ff"><circle cx="70" cy="70" r="5"/></g>
            <rect x="1" y="50" width="5" height="5" style="fill:#abc"/>""")
        assertEquals(listOf("#00ff00", "#ff0000", "#0000ff", "#aabbcc"), r.items.map { it.layerKey })
    }

    @Test fun `a frame around other shapes stays a separate part`() {
        val r = parse("""<rect x="0" y="0" width="90" height="90" fill="none" stroke="#000"/>$square fill="none" stroke="#000"/>""")
        assertEquals(2, r.items.size)
    }

    @Test fun `a letter keeps its hole inside one path`() {
        val r = parse("""<path d="M0 0H20V20H0Z M5 5H15V15H5Z" fill="#000"/>""")
        assertEquals(1, r.items.size)
        assertEquals(2, r.items[0].polys.size)
    }

    @Test fun `a group around everything is dropped, inner groups stay`() {
        val r = parse("""<g><g>$square/>$other/></g><g><rect x="70" y="70" width="5" height="5"/></g></g>""")
        val g = r.items.map { it.groups.first() }
        assertEquals(g[0], g[1])
        assertTrue(g[0] != g[2])
    }

    @Test fun `without any group the import is one group`() {
        val r = parse("""$square/>$other/>""")
        assertEquals(listOf("*"), r.items.flatMap { it.groups }.distinct())
    }

    @Test fun `white starts hidden`() {
        val r = parse("""<rect width="100" height="100" fill="#fff"/>$square stroke="#000" fill="none"/>""")
        assertFalse(r.layers.first { it.key == "#ffffff" }.visible)
        assertTrue(r.layers.first { it.key == "#000000" }.visible)
    }

    @Test fun `what is left out is reported, hidden things are not`() {
        val r = parse("""$square/><text x="0" y="0">Hallo</text><use href="#a"/><image href="bild.png" width="5" height="5"/>""")
        assertEquals(listOf("Text (1)", "verlinkte Bilder (1)", "Klone (1)"), r.skipped)
        assertEquals(1, parse("""$square/><rect width="5" height="5" style="display:none"/><rect width="5" height="5" visibility="hidden"/>""").items.size)
    }

    @Test fun `embedded picture comes along with its box`() {
        val data = java.util.Base64.getEncoder().encodeToString(ByteArray(20) { it.toByte() })
        val r = parse("""$square/><image x="10" y="20" width="30" height="40" href="data:image/png;base64,$data"/>""")
        assertEquals(1, r.images.size)
        assertEquals(Box(10.0, 20.0, 40.0, 60.0), r.images[0].box)
    }

    @Test fun `gradients import without a layer`() {
        assertNull(SvgImport.colour("url(#g)", "#000000"))
        assertEquals("#102030", SvgImport.colour("rgb(16, 32, 48)", null))
        assertEquals("none", SvgImport.colour("none", null))
    }

    private fun square(x: Double, s: Double) = listOf(Pt(x, 0.0), Pt(x + s, 0.0), Pt(x + s, s), Pt(x, s), Pt(x, 0.0))

    @Test fun `splitting separates contours first, then the lines, in place`() {
        val outer = square(0.0, 20.0)
        val hole = outer.map { Pt(it.x / 4 + 5, it.y / 4 + 5) }
        val e = Element(layerId = "l", kind = "x", transform = Transform(100.0, 50.0), paths = listOf(outer, hole, square(30.0, 5.0)), groupId = "g", plate = 1)
        val parts = e.splitParts()
        assertEquals(2, parts.size)
        assertEquals(Box(100.0, 50.0, 120.0, 70.0), parts[0].worldBounds())
        assertEquals(Box(130.0, 50.0, 135.0, 55.0), parts[1].worldBounds())
        assertTrue(parts.all { it.layerId == "l" && it.groupId == "g" && it.plate == 1 })
        val lines = parts[0].splitParts()
        assertEquals(2, lines.size)
        assertEquals(Box(105.0, 55.0, 110.0, 60.0), lines[1].worldBounds())
    }

    @Test fun `text, pictures and single lines stay whole`() {
        val line = Element(layerId = "l", kind = "x", paths = listOf(square(0.0, 5.0)))
        assertEquals(listOf(line), line.splitParts())
        val text = Element(layerId = "l", kind = "x", text = "Hi", paths = listOf(square(0.0, 5.0), square(9.0, 5.0)))
        assertEquals(listOf(text), text.splitParts())
    }
}
