package de.millione.lumacut.core

import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class XsTest {
    private fun zip(vararg files: Pair<String, String>): ByteArray {
        val out = ByteArrayOutputStream()
        ZipOutputStream(out).use { z -> for ((n, c) in files) { z.putNextEntry(ZipEntry(n)); z.write(c.toByteArray()); z.closeEntry() } }
        return out.toByteArray()
    }

    private val project = """{"activeCanvasId":"c1","modules":{"canvases":["c1"]}}"""
    private val canvas = """{"id":"c1","layerData":{"#fe0002":{"name":"#FE0002","order":1,"visible":true},"#000000":{"name":"#000000","order":2,"visible":true}}}"""

    private fun display(id: String, type: String = "PATH", x: Double, y: Double, d: String, skewX: Double = 0.0, localSkewX: Double = 0.0,
                        layer: String = "#000000", fill: Boolean = false, groups: String = "[]", scale: String = """{"x":1,"y":1}""") =
        """{"id":"$id","type":"$type","x":$x,"y":$y,"angle":0,"scale":$scale,"skew":{"x":$skewX,"y":0},"localSkew":{"x":$localSkewX,"y":0},
            "layerTag":"$layer","groupTags":$groups,"fill":{"visible":$fill},"stroke":{"visible":true},"dPath":"$d"}"""

    private fun xs(vararg displays: String) = zip(
        ".format" to "v2", "project.json" to project, "canvases/c1.json" to canvas,
        "canvases/c1/displays-0.json" to """{"displays":[${displays.joinToString(",")}]}""")

    @Test fun `type is recognised and plain placement puts x y at the top left`() {
        val bytes = xs(display("a", x = 100.0, y = 50.0, d = "M 5 5 L 25 5 L 25 15 L 5 15 Z", layer = "#fe0002", groups = """["g1"]"""))
        assertEquals(FileKind.XS, FileKinds.detect(bytes))
        val r = ImportFormats.parseVector(FileKind.XS, bytes)
        assertEquals(1, r.items.size)
        assertEquals(Box(100.0, 50.0, 120.0, 60.0), boundsOf(r.polys))
        assertEquals("#fe0002", r.items[0].layerKey); assertEquals(listOf("g1"), r.items[0].groups)
        assertEquals(listOf("#FE0002"), r.layers.map { it.name })
    }

    @Test fun `skew pi with local skew pi cancel out and x y is the lower edge`() {
        val pi = 3.141593
        // scale 2 x 3, outline 10 x 4 -> 20 x 12; asymmetric so a wrong mirror would show
        val bytes = xs(display("a", x = 200.0, y = 100.0, d = "M 0 0 L 10 0 L 10 1 L 0 4", skewX = pi, localSkewX = pi, scale = """{"x":2,"y":3}"""))
        val polys = ImportFormats.parseVector(FileKind.XS, bytes).polys
        val b = boundsOf(polys)!!
        assertEquals(20.0, b.width, 1e-3); assertEquals(12.0, b.height, 1e-3)
        assertEquals(200.0, b.minX, 1e-3); assertEquals(88.0, b.minY, 1e-3); assertEquals(100.0, b.maxY, 1e-3)   // y is the bottom edge
        // the outline is not mirrored overall: (10,0) stays at the top (y = 88), (10,1) is 3 mm below it
        assertTrue(polys[0].any { kotlin.math.abs(it.x - 220.0) < 1e-3 && kotlin.math.abs(it.y - 88.0) < 1e-3 })
        assertTrue(polys[0].any { kotlin.math.abs(it.x - 220.0) < 1e-3 && kotlin.math.abs(it.y - 91.0) < 1e-3 })
        assertTrue(polys[0].any { kotlin.math.abs(it.x - 200.0) < 1e-3 && kotlin.math.abs(it.y - 100.0) < 1e-3 })
    }

    @Test fun `single mirror flips y, chunks are all read, hidden and unknown are handled`() {
        val flip = 3.141593
        val one = ImportFormats.parseVector(FileKind.XS, xs(display("a", x = 10.0, y = 10.0, d = "M 0 0 L 10 0 L 10 2 L 0 6", localSkewX = flip))).polys
        val b = boundsOf(one)!!
        assertEquals(10.0, b.minX, 1e-3); assertEquals(10.0, b.minY, 1e-3); assertEquals(16.0, b.maxY, 1e-3)    // flipped, then top-left at x y
        assertTrue(one[0].any { kotlin.math.abs(it.x - 20.0) < 1e-3 && kotlin.math.abs(it.y - 14.0) < 1e-3 }, "(10,2) became (10,4) of the flipped outline")
        val files = arrayOf(".format" to "v2", "project.json" to project, "canvases/c1.json" to canvas,
            "canvases/c1/displays-0.json" to """{"displays":[${display("a", x = 0.0, y = 0.0, d = "M 0 0 L 5 0")}]}""",
            "canvases/c1/displays-1.json" to """{"displays":[${display("b", x = 30.0, y = 0.0, d = "M 0 0 L 5 0", fill = true)},
                {"id":"t","type":"TEXT","x":0,"y":0,"width":20,"height":5,"text":"Hallo"},
                {"id":"h","type":"PATH","visible":false,"x":0,"y":0,"dPath":"M 0 0 L 9 9"}]}""")
        val r = ImportFormats.parseVector(FileKind.XS, zip(*files))
        assertEquals(2, r.items.size); assertTrue(!r.items[0].fill && r.items[1].fill)
        assertEquals(listOf("1× Text"), r.skipped)
        assertEquals("Übersprungen: 1× Text (in Pfade bzw. Bild umwandeln)", r.skippedSentence())
    }

    @Test fun `rect and circle use their size, bitmaps become pictures, bad files are refused`() {
        val png = java.util.Base64.getEncoder().encodeToString(ByteArray(80) { 3 })
        val bytes = xs(
            """{"id":"r","type":"RECT","x":10,"y":20,"width":30,"height":10,"layerTag":"#000000","fill":{"visible":false}}""",
            """{"id":"c","type":"CIRCLE","x":60,"y":20,"width":8,"height":8,"layerTag":"#000000"}""",
            """{"id":"b","type":"BITMAP","x":0,"y":50,"width":15,"height":12,"base64":"data:image/png;base64,$png"}""")
        val r = ImportFormats.parseVector(FileKind.XS, bytes)
        assertEquals(2, r.items.size); assertEquals(1, r.images.size)
        assertEquals(Box(10.0, 20.0, 40.0, 30.0), boundsOf(listOf(r.items[0].polys[0])))
        assertEquals(Box(0.0, 50.0, 15.0, 62.0), r.images[0].box)
        assertEquals(FileKind.UNKNOWN, FileKinds.detect(zip("readme.txt" to "hallo")))
        assertFailsWith<ImportException> { Xs.parse(zip("readme.txt" to "hallo")) }
        assertFailsWith<ImportException> { Xs.parse(zip("project.json" to project, "canvases/c1.json" to canvas)) }
    }

    @Test fun `xcs uses the same placement`() {
        val json = """{"canvas":[{"layerData":{"#000000":{"name":"Schwarz","order":1}},"displays":[
            {"type":"PATH","x":40,"y":40,"width":10,"height":10,"layerTag":"#000000","dPath":"M 0 0 L 10 0 L 10 10 Z"}]}]}"""
        val r = Xcs.parse(json.toByteArray())
        assertEquals(Box(40.0, 40.0, 50.0, 50.0), boundsOf(r.polys)); assertEquals("Schwarz", r.layers[0].name)
    }
}

class ImportLayoutTest {
    private fun rectItem(x: Double, y: Double, w: Double, h: Double, group: String? = null) =
        ImportItem(listOf(Shapes.rect(w, h).map { Pt(it.x + x, it.y + y) }), null, false, listOfNotNull(group), null)

    private fun result(vararg items: ImportItem) = VectorImport(items.flatMap { it.polys }, emptyList(), emptyList(), items.toList())

    @Test fun `small import stays 1 to 1 and is centred`() {
        val units = ImportLayout.units(result(rectItem(0.0, 0.0, 100.0, 50.0)))
        val l = ImportLayout.arrange(units)
        assertEquals(FitKind.AS_IS, l.kind)
        assertEquals(Pt(130.0, 145.0), l.offsets[0])
    }

    @Test fun `groups that do not fit together are packed in rows with 5 mm gaps`() {
        // three 200 x 150 groups: 200+5+200 > 360, so one per row; 3 rows of 150 + 2 gaps does not fit in 340 -> two rows
        val units = ImportLayout.units(result(rectItem(0.0, 0.0, 170.0, 150.0, "a"), rectItem(500.0, 0.0, 170.0, 150.0, "b"), rectItem(0.0, 500.0, 170.0, 150.0, "c")))
        assertEquals(3, units.size)
        val l = ImportLayout.arrange(units)
        // 170 + 5 + 170 = 345 <= 358 fits in a row; two rows of 150 + 5 = 305 <= 338
        assertEquals(FitKind.PACKED, l.kind)
        val placed = l.units.indices.map { i -> l.units[i].box.let { b -> Box(b.minX + l.offsets[i]!!.x, b.minY + l.offsets[i]!!.y, b.maxX + l.offsets[i]!!.x, b.maxY + l.offsets[i]!!.y) } }
        assertTrue(placed.all { Work.contains(it) })
        for (i in placed.indices) for (j in i + 1 until placed.size) {
            val a = placed[i]; val b = placed[j]
            assertTrue(a.maxX + 4.99 <= b.minX || b.maxX + 4.99 <= a.minX || a.maxY + 4.99 <= b.minY || b.maxY + 4.99 <= a.minY, "gap between $i and $j")
        }
        assertEquals(1.0 + 150.0 + 5.0, placed.maxOf { it.minY }, 1e-9)
    }

    @Test fun `parts that cannot be placed are reported, shrink factor is offered`() {
        val units = ImportLayout.units(result(rectItem(0.0, 0.0, 400.0, 100.0, "a"), rectItem(0.0, 200.0, 100.0, 100.0, "b")))
        val l = ImportLayout.arrange(units)
        assertEquals(FitKind.PARTIAL, l.kind); assertEquals(1, l.leftOut)
        assertNotNull(l.offsets[1]); assertEquals(null, l.offsets[0])
        val k = ImportLayout.shrinkFactor(units)
        assertEquals((360.0 - 10) / 400.0, k, 1e-9)
    }

    @Test fun `one big group falls back to its parts`() {
        val units = ImportLayout.units(result(rectItem(0.0, 0.0, 200.0, 200.0, "g"), rectItem(300.0, 0.0, 100.0, 100.0, "g")))
        assertEquals(1, units.size)
        val l = ImportLayout.arrange(units)
        assertEquals(2, l.units.size); assertEquals(FitKind.PACKED, l.kind)
    }

    @Test fun `unstructured imports become one group of parts`() {
        val r = VectorImport(listOf(Shapes.rect(10.0, 10.0), Shapes.rect(10.0, 10.0).map { Pt(it.x + 30, it.y) }), emptyList(), emptyList())
        val units = ImportLayout.units(r)
        assertEquals(1, units.size); assertEquals(2, units[0].items.size)
    }
}

class CutOrderTest {
    @Test fun `inner contours are cut before the contour around them`() {
        val layers = Document.defaultLayers()
        val cut = layers[2].copy(passes = 1, zStepMm = 0.0)
        val outer = Element(layerId = cut.id, kind = "Außen", transform = Transform(50.0, 50.0), paths = listOf(Shapes.rect(100.0, 100.0)))
        val inner = Element(layerId = cut.id, kind = "Innen", transform = Transform(80.0, 80.0), paths = listOf(Shapes.rect(20.0, 20.0)))
        val line = Element(layerId = cut.id, kind = "Linie", transform = Transform(120.0, 120.0), paths = listOf(listOf(Pt(0.0, 0.0), Pt(10.0, 0.0))))
        val g = MarlinWriter().write(Document(layers = listOf(cut), elements = listOf(outer, inner, line)))
        val tp = Toolpath.parse(g)
        val cuts = tp.segments.filter { it.cut }
        // machine X = 390 - x: outer spans X 240..340, inner/line lie in X 270..310
        fun isOuter(s: Segment) = s.x0 < 255 || s.x0 > 325 || s.y0 < 85 || s.y0 > 165
        val lastInner = cuts.indexOfLast { !isOuter(it) }
        val firstOuter = cuts.indexOfFirst { isOuter(it) }
        assertTrue(firstOuter > lastInner, "outer contour must come last (first outer $firstOuter, last inner $lastInner)")
        assertEquals(cuts.size, cuts.count { true })
    }

    @Test fun `ordering helper keeps all paths and handles nesting levels`() {
        val big = Shapes.rect(100.0, 100.0)
        val mid = Shapes.rect(50.0, 50.0).map { Pt(it.x + 10, it.y + 10) }
        val small = Shapes.rect(10.0, 10.0).map { Pt(it.x + 20, it.y + 20) }
        val order = orderForCutting(listOf(big, mid, small), Pt(0.0, 0.0))
        assertEquals(3, order.size)
        assertEquals(listOf(small, mid, big), order)
        assertEquals(2, orderForCutting(listOf(big, small), Pt(0.0, 0.0)).let { it.size })
    }
}
