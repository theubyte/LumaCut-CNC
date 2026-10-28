package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class DxfImportTest {
    private fun dxf(vararg entities: String, units: Int = 4) = buildString {
        append("0\nSECTION\n2\nHEADER\n9\n\$INSUNITS\n70\n$units\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n")
        entities.forEach { append(it) }
        append("0\nENDSEC\n0\nEOF\n")
    }.toByteArray()

    @Test fun `lines circles and units, Y flipped downwards`() {
        val polys = DxfImport.parse(dxf(
            "0\nLINE\n8\n0\n10\n0\n20\n0\n11\n10\n21\n0\n",
            "0\nCIRCLE\n8\n0\n10\n5\n20\n20\n40\n2\n",
        ))
        assertEquals(2, polys.size)
        val b = boundsOf(polys)!!
        assertEquals(0.0, b.minX, 1e-6); assertEquals(10.0, b.maxX, 1e-6); assertEquals(22.0, b.height, 0.01)
        assertEquals(b.maxY, polys[0][0].y, 1e-9, "DXF y=0 is at the bottom")
        assertEquals(2 * PI * 2, polys[1].length(), 0.05)
        val inch = DxfImport.parse(dxf("0\nLINE\n10\n0\n20\n0\n11\n1\n21\n0\n", units = 1))
        assertEquals(25.4, inch[0].length(), 1e-6)
    }

    @Test fun `lwpolyline with bulge is a half circle`() {
        val polys = DxfImport.parse(dxf("0\nLWPOLYLINE\n90\n2\n70\n0\n10\n0\n20\n0\n42\n1\n10\n10\n20\n0\n"))
        assertEquals(PI * 5, polys[0].length(), 0.05)
    }

    @Test fun `blocks are inserted with offset, scale and rotation`() {
        val text = "0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nB1\n0\nLINE\n10\n0\n20\n0\n11\n10\n21\n0\n0\nENDBLK\n0\nENDSEC\n" +
            "0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nB1\n10\n100\n20\n100\n41\n2\n42\n2\n50\n90\n0\nINSERT\n2\nB1\n10\n0\n20\n0\n0\nENDSEC\n0\nEOF\n"
        val polys = DxfImport.parse(text.toByteArray())
        assertEquals(2, polys.size)
        assertEquals(20.0, polys[0].length(), 1e-6)
        assertEquals(0.0, polys[0][1].x - polys[0][0].x, 1e-6, "rotated by 90°")
    }

    @Test fun `garbage is refused`() {
        assertFailsWith<DxfException> { DxfImport.parse("hello".toByteArray()) }
        assertFailsWith<DxfException> { DxfImport.parse(dxf("0\nTEXT\n1\nHallo\n")) }
    }
}

class HeightMapTest {
    @Test fun `grid, bilinear and fill`() {
        val m = HeightMap.grid("A", Box(100.0, 100.0, 140.0, 120.0), spacingMm = 10.0, marginMm = 0.0)
        assertEquals(5, m.cols); assertEquals(3, m.rows)
        val pts = m.points()
        assertEquals(Pt(140.0, 110.0), pts[5].second, "serpentine: row 1 runs right to left")
        val z = List(m.cols * m.rows) { i -> 3.0 + (i % m.cols) * 0.1 }
        val full = m.copy(z = z)
        assertEquals(3.15, full.at(Pt(115.0, 105.0)), 1e-9)
        val holes = full.copy(z = z.mapIndexed { i, v -> if (i == 7) Double.NaN else v }).filled()
        assertTrue(holes.z.none { it.isNaN() })
    }

    @Test fun `focus compensation follows the surface and never comes closer than 2 mm`() {
        val map = HeightMap("A", 0.0, 0.0, 100.0, 100.0, 2, 2, listOf(3.0, 4.0, 3.0, 4.0))   // tilts 1 mm over 100 mm in X
        val line = Document.defaultLayers()[1]
        val gcode = MarlinWriter().write(Document(layers = listOf(line), elements = listOf(
            Element(layerId = line.id, kind = "Linie", paths = listOf(listOf(Pt(0.0, 50.0), Pt(100.0, 50.0)))))))
        val (out, report) = FocusCompensation.apply(gcode, HeightMapSet(listOf(map)), focusGapMm = 7.0, tipOffsetMm = 1.5)
        assertEquals(50, report.segments)              // 100 mm in 2 mm pieces
        assertEquals(8.5, report.minZ, 1e-6)           // surface 3.0 at x=0 + 5.5
        assertEquals(9.5, report.maxZ, 1e-6)
        assertTrue(out.lines().filter { it.startsWith("G1") }.all { Regex("Z[\\d.]+ F\\d+ S\\d+$").containsMatchIn(it) }, out)
        assertTrue(report.warnings.isEmpty())
        assertFailsWith<IllegalArgumentException> { FocusCompensation.apply("G2 X40 Y40 I1 J0\n", HeightMapSet(listOf(map)), 7.0, 1.5) }
    }

    @Test fun `per-pass drop becomes a z offset`() {
        val layer = Document.defaultLayers()[2].copy(passes = 2, zStepMm = 1.0)
        val gcode = MarlinWriter().write(Document(layers = listOf(layer), elements = listOf(
            Element(layerId = layer.id, kind = "Linie", paths = listOf(listOf(Pt(10.0, 10.0), Pt(12.0, 10.0)))))))
        val flat = HeightMap("A", 0.0, 0.0, 50.0, 50.0, 2, 2, listOf(3.0, 3.0, 3.0, 3.0))
        val (out, _) = FocusCompensation.apply(gcode, HeightMapSet(listOf(flat)), 7.0, 1.5)
        assertTrue("G91" !in out && "G0 Z-" !in out)
        val zs = out.lines().filter { it.startsWith("G1") }.map { Regex("Z([\\d.]+)").find(it)!!.groupValues[1].toDouble() }
        assertEquals(listOf(8.5, 7.5), zs)
    }
}

class ScanPlanTest {
    // A camera that sees 60 x 45 mm centred 20 mm in front of the laser, 1 px = 0.1 mm.
    private val cal = CameraCalibration.fromRectangle(600, 450,
        listOf(Pt(0.0, 0.0), Pt(600.0, 0.0), Pt(600.0, 450.0), Pt(0.0, 450.0)),
        listOf(Pt(170.0, 172.5), Pt(230.0, 172.5), Pt(230.0, 217.5), Pt(170.0, 217.5)),
        head = Pt(200.0, 175.0), scanZ = 25.0)

    @Test fun `calibration maps pixels to work mm relative to the head`() {
        assertEquals(Pt(100.0, 120.0), cal.pixelToWork(Pt(300.0, 225.0), Pt(100.0, 100.0)).let { Pt(Math.round(it.x * 1e6) / 1e6, Math.round(it.y * 1e6) / 1e6) })
        val back = cal.workToPixel(Pt(100.0, 120.0), Pt(100.0, 100.0))
        assertEquals(300.0, back.x, 1e-6); assertEquals(225.0, back.y, 1e-6)
    }

    @Test fun `tile plan covers the work area within head travel`() {
        val plan = Scan.plan(cal, overlap = 0.25)
        assertTrue(plan.heads.size > 20)
        assertTrue(plan.uncovered.isEmpty(), plan.uncovered.toString())
        assertTrue(plan.heads.all { it.x >= 0.0 && it.y >= -Bed.SAFE && it.x <= Bed.WIDTH && it.y <= Bed.HEIGHT - Bed.SAFE })
    }

    @Test fun `mosaic places a tile pixel at the right work position`() {
        val px = IntArray(600 * 450) { 0xFF000000.toInt() or (it % 600) }
        val tile = Scan.Tile(px, 600, 450, Pt(100.0, 100.0))
        val (img, w, _) = Scan.mosaic(listOf(tile), cal, pxPerMm = 1.0)
        // output pixel (100,120) samples work (100.5,120.5) = photo x 305 -> between columns 304 and 305
        assertTrue((img[120 * w + 100] and 0xFF) in listOf(304 and 0xFF, 305 and 0xFF))
        assertEquals(0, img[5 * w + 5], "outside the tile stays transparent")
    }

    @Test fun `probe reachability follows the Pi rule`() {
        val offset = Pt(-23.0, 15.0)
        assertTrue(Scan.reachable(Pt(100.0, 100.0), offset))
        assertTrue(!Scan.reachable(Pt(5.0, 100.0), offset), "head would need machine X > 390")
        assertTrue(Scan.reachable(Pt(100.0, 2.0), offset), "upper edge: head may enter the safezone while probing")
    }
}

class ScanLevelTest {
    private fun grey(v: Int) = (0xFF shl 24) or (v shl 16) or (v shl 8) or v
    private fun lum(c: Int) = (c shr 8) and 255

    @Test fun `slow light change goes, marks keep their contrast`() {
        val w = 400; val h = 300
        // background falls from 200 on the left to 80 on the right; dark marks at 40 % of it
        val px = IntArray(w * h) { q -> val x = q % w; val y = q / w
            val bg = 200 - 120 * x / (w - 1)
            grey(if (x % 50 in 20..22 && y % 60 in 10..40) bg * 4 / 10 else bg) }
        px[5] = 0   // an uncovered pixel stays transparent
        val out = Scan.level(px, w, h, pxPerMm = 4.0)
        assertEquals(0, out[5])
        val left = lum(out[150 * w + 10]); val right = lum(out[150 * w + 390])
        assertTrue(kotlin.math.abs(left - right) <= 12, "even background: $left vs $right")
        val mark = lum(out[20 * w + 371]); val beside = lum(out[20 * w + 380])
        assertTrue(mark < beside * 0.55, "mark still dark: $mark vs $beside")
    }
}
