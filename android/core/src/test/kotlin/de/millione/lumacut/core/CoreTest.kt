package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.math.PI
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PiClientTest {
    private fun server(vararg bodies: Pair<Int, String>) = MockWebServer().apply {
        bodies.forEach { (code, body) -> enqueue(MockResponse().setResponseCode(code).setBody(body)) }
        start()
    }

    @Test fun `status from the real Pi format`() = runBlocking {
        val body = """{"connected":true,"state":"Idle","owner":"Frei","homed":true,"position":[0.0,0.0,20.0],
            "workpiece_surface_z":3.2,"laser_focus_z":8.7,"probe_xy_offset_mm":[-23.0,15.0],
            "job":{"file":"a.gcode","state":"running","line":50,"total":200,"error":""},
            "config":{"validated":true,"z_clearance_mm":20.0,"focus_gap_mm":7.0,"z_switch_tip_offset_mm":1.5,
            "probe_offset_x_mm":-23.0,"probe_offset_y_mm":15.0,"travels":{"x":390.0}},
            "firmware_update":{"state":"idle","progress":0,"message":""},"unknown_new_field":42,"io":{"x":"y"}}"""
        val srv = server(200 to body)
        val s = PiClient("127.0.0.1", srv.port).status()
        assertTrue(s.connected && s.homed && s.ownerFree)
        assertEquals(Pt(-23.0, 15.0), s.probeOffset)
        assertEquals(0.25, s.job.fraction)
        assertTrue(s.job.active)
        assertEquals(7.0, s.config.focus_gap_mm)
        srv.shutdown()
    }

    @Test fun `moveto and camera snapshot`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"message":"Kopf auf X60.0 Y45.5"}"""))
            enqueue(MockResponse().setBody(okio.Buffer().write(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2))))
            enqueue(MockResponse().setResponseCode(503).setBody("""{"error":"Keine Kamera am Pi"}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        pi.moveTo(60.0, 45.5)
        assertEquals("op=moveto&x=60.000&y=45.500", srv.takeRequest().body.readUtf8())
        assertEquals(4, pi.cameraSnapshot(640, 480).size)
        assertEquals("/api/camera/snapshot?w=640&h=480", srv.takeRequest().path)
        assertEquals("Keine Kamera am Pi", assertFailsWith<PiException> { pi.cameraSnapshot() }.message)
        srv.shutdown()
    }

    @Test fun `action posts form and returns the message, errors carry the Pi text`() = runBlocking {
        val srv = server(200 to """{"message":"Bewegung ausgeführt"}""", 400 to """{"error":"Maschine nicht referenziert"}""")
        val pi = PiClient("127.0.0.1", srv.port)
        assertEquals("Bewegung ausgeführt", pi.action("jog", mapOf("axis" to "X", "distance" to "1.0")))
        val req = srv.takeRequest()
        assertEquals("/api/action", req.path)
        assertEquals("op=jog&axis=X&distance=1.0", req.body.readUtf8())
        val e = assertFailsWith<PiException> { pi.action("home") }
        assertEquals("Maschine nicht referenziert", e.message)
        srv.shutdown()
    }

    @Test fun `upload is multipart with the file name`() = runBlocking {
        val srv = server(200 to """{"message":"gespeichert"}""")
        PiClient("127.0.0.1", srv.port).uploadJob("Schild.gcode", "G21\n")
        val req = srv.takeRequest()
        assertEquals("/api/upload", req.path)
        val text = req.body.readUtf8()
        assertTrue("filename=\"Schild.gcode\"" in text && "G21" in text)
        srv.shutdown()
    }

    @Test fun `address accepts IP, host name and URL`() {
        assertEquals("http://192.168.2.89:8080/", PiClient.baseUrl("192.168.2.89").toString())
        assertEquals("http://192.168.2.89:9000/", PiClient.baseUrl(" 192.168.2.89:9000 ").toString())
        assertEquals("http://lumacut.local:8080/", PiClient.baseUrl("lumacut.local").toString())
        assertEquals("http://lumacut:8080/", PiClient.baseUrl("lumacut").toString())
        assertEquals("http://lumacut.fritz.box/", PiClient.baseUrl("http://lumacut.fritz.box/").toString())
        assertEquals("https://laser.example.com/lumacut", PiClient.baseUrl("https://laser.example.com/lumacut").toString())
        for (bad in listOf("", "ftp://192.168.2.89", "laser.example.com", "http://8.8.8.8", "http://u:p@lumacut.local", "lumacut.local/?x=1"))
            assertFailsWith<IllegalArgumentException>(bad) { PiClient.baseUrl(bad) }
    }

    @Test fun `requests go below the URL path`() = runBlocking {
        val srv = MockWebServer()
        srv.enqueue(MockResponse().setBody("""{"files":[]}"""))
        srv.start()
        PiClient("http://127.0.0.1:${srv.port}/lumacut/").jobs()
        assertEquals("/lumacut/api/jobs", srv.takeRequest().path)
        srv.shutdown()
    }

    @Test fun `only LAN addresses, unknown actions and bad names refused`() {
        assertTrue(PiClient.isLocalIpv4("192.168.2.89"))
        assertTrue(!PiClient.isLocalIpv4("8.8.8.8") && !PiClient.isLocalIpv4("lumacut.local"))
        assertFailsWith<IllegalArgumentException> { PiClient("1.1.1.1") }
        assertFailsWith<IllegalArgumentException> { PiClient("http://laser.example.com") }
        assertFailsWith<IllegalArgumentException> { runBlocking { PiClient("127.0.0.1", 1).action("M42") } }
        assertFailsWith<IllegalArgumentException> { PiClient.checkJobName("../x.gcode") }
        assertEquals("Namensschild-fuer-Maerz.gcode", PiClient.jobNameFrom("Namensschild für März"))
    }
}

class ToolpathTest {
    private val square = "G21\nG90\nM5 I\nM3 I\nG0 X40 Y40\nG1 X60 Y40 F1200 S128\nG1 X60 Y60 S128\nG1 X40 Y60 S128\nG1 X40 Y40 S128\nM5 I\nM400\n"

    @Test fun `square stats and time`() {
        val t = Toolpath.parse(square)
        assertEquals(80.0, t.stats.cutMm, 1e-9)
        assertEquals(Box(40.0, 40.0, 60.0, 60.0), t.bounds)
        assertEquals(128, t.stats.maxPower)
        val expected = 80.0 / 1200 * 60 + kotlin.math.hypot(40.0, 40.0) / 9000 * 60 + 4 * 0.02
        assertEquals(expected, t.stats.seconds, 1e-6)
        assertTrue(t.stats.warnings.isEmpty())
    }

    @Test fun `Marlin semantics and arcs`() {
        val t = Toolpath.parse("M3 I\nG0 X40 Y40\nG1 X50 S100 F600\nG0 X40 Y50\nG1 X50\n")
        assertEquals(1, t.segments.count { it.cut })
        assertTrue(t.stats.warnings.first().contains("ohne S-Wert"))
        val arc = Toolpath.parse("M3 I\nG0 X50 Y40\nG3 X40 Y50 I-10 J0 S80 F600\n")
        assertEquals(PI * 5, arc.stats.cutMm, 0.05)
        assertNull(Toolpath.parse("G0 X40 Y40\nG1 X60 S200 F600\n").bounds)
        assertEquals("2 min 05 s", formatDuration(125.0))
    }
}

class MarlinWriterTest {
    private fun doc(vararg elements: Element, layers: List<Layer> = Document.defaultLayers()) =
        Document(title = "Test", layers = layers, elements = elements.toList())

    @Test fun `shape starting at the work-area edge still begins with a rapid`() {
        // A rectangle dragged from outside is clamped to work x 0. The head
        // position is unknown, so the first burn must not start from wherever it is.
        val layers = Document.defaultLayers()
        val line = layers.first { it.mode == LayerMode.LINE }
        val rect = Element(layerId = line.id, kind = "Rechteck", transform = Transform(0.0, 40.0), paths = listOf(Shapes.rect(360.0, 300.0)))
        val gcode = MarlinWriter().write(doc(rect, layers = layers))
        val moves = gcode.lines().filter { it.startsWith("G0 ") || it.startsWith("G1 ") }
        assertTrue(moves.first().startsWith("G0 X370.000 Y40.000"), moves.first())
        val tp = Toolpath.parse(gcode)
        assertTrue(tp.stats.warnings.isEmpty(), tp.stats.warnings.toString())
        assertEquals(Box(10.0, 40.0, 370.0, 340.0), tp.bounds)
    }

    @Test fun `nothing is burnt in the park corner`() {
        val layers = Document.defaultLayers()
        val line = layers.first { it.mode == LayerMode.LINE }
        // top right on screen = machine 0/0 (limit switches)
        val inCorner = Element(layerId = line.id, kind = "Rechteck", transform = Transform(Work.WIDTH - 40.0, 5.0), paths = listOf(Shapes.rect(20.0, 10.0)))
        assertFailsWith<JobBuildException> { MarlinWriter().write(doc(inCorner, layers = layers)) }
        val below = inCorner.copy(transform = Transform(Work.WIDTH - 40.0, 40.0))
        assertPiCompatible(MarlinWriter().write(doc(below, layers = layers)))
    }

    private fun rect(layer: Layer, x: Double, y: Double, w: Double = 20.0, h: Double = 10.0) =
        Element(layerId = layer.id, kind = "Rechteck", transform = Transform(x, y), paths = listOf(Shapes.rect(w, h)))

    /** Every line must be acceptable for the Pi's MarlinLaserGuard. */
    private fun assertPiCompatible(gcode: String) {
        val allowed = Regex("""^(G21|G90|G91|M5 I|M3 I|M400|G0 X[\d.]+ Y[\d.]+|G0 Z-?[\d.]+ F600|G1 X[\d.]+ Y[\d.]+ F\d+ S\d+)$""")
        for (line in gcode.lines().filter { it.isNotBlank() && !it.startsWith(";") }) {
            assertTrue(allowed.matches(line), "Pi würde ablehnen: $line")
            assertTrue(line.length <= 96)
        }
        assertEquals(1, gcode.lines().count { it == "M3 I" }, "genau ein M3 I")
    }

    /** No XY position of the job — burning or not — may leave the machine travel. */
    private fun assertInsideTravel(gcode: String) {
        for (m in Regex("""X([\d.]+) Y([\d.]+)""").findAll(gcode)) {
            val x = m.groupValues[1].toDouble(); val y = m.groupValues[2].toDouble()
            assertTrue(x >= -1e-9 && y >= -1e-9 && x <= Bed.WIDTH && y <= Bed.HEIGHT, "außerhalb des Fahrwegs: ${m.value}")
        }
    }

    @Test fun `work area is turned by 180 degrees into machine coordinates`() {
        val layers = Document.defaultLayers()
        val cut = layers[2]
        val g = MarlinWriter("t").write(doc(rect(cut, 100.0, 100.0), layers = layers))
        assertPiCompatible(g)
        val t = Toolpath.parse(g)
        assertEquals(2 * 60.0, t.stats.cutMm, 1e-6)       // 2 passes
        assertEquals(217, t.stats.maxPower)                // 85 % of 255
        assertEquals(Box(250.0, 100.0, 270.0, 110.0), t.bounds)   // x: 370 - 120..100, y: 100..110
    }

    @Test fun `fill overscan stays inside the work area`() {
        val layers = Document.defaultLayers()
        val fill = layers[0].copy(intervalMm = 1.0, overscanMm = 5.0)
        val g = MarlinWriter().write(doc(rect(fill, 0.0, 0.0, 20.0, 10.0), rect(fill, 340.0, 330.0, 20.0, 10.0), layers = listOf(fill)))
        assertPiCompatible(g)
        assertInsideTravel(g)
        val t = Toolpath.parse(g)
        assertEquals(2 * 10 * 20.0, t.stats.cutMm, 1e-6)
        assertTrue("G0 X370.000 Y0.500" in g, "run-up clipped at the work area edge (work x 0 = machine X 370)")
    }

    @Test fun `focus drops between passes and returns afterwards`() {
        val layers = Document.defaultLayers()
        val cut = layers[2].copy(passes = 3, zStepMm = 0.8)
        val g = MarlinWriter().write(doc(rect(cut, 50.0, 50.0), layers = listOf(cut)))
        assertPiCompatible(g)
        assertEquals(2, g.lines().count { it == "G0 Z-0.800 F600" })
        assertTrue("G0 Z1.600 F600" in g)
        val tooDeep = cut.copy(passes = 5, zStepMm = 1.0)
        assertFailsWith<JobBuildException> { MarlinWriter().write(doc(rect(tooDeep, 50.0, 50.0), layers = listOf(tooDeep))) }
    }

    @Test fun `elements outside the work area and hidden layers`() {
        val layers = Document.defaultLayers()
        val e = assertFailsWith<JobBuildException> { MarlinWriter().write(doc(rect(layers[1], 360.0, 100.0), layers = layers)) }
        assertTrue(e.message!!.contains("Arbeitsfläche"))
        val hidden = layers.map { it.copy(visible = false) }
        assertFailsWith<JobBuildException> { MarlinWriter().write(doc(rect(hidden[1], 10.0, 10.0), layers = hidden)) }
        assertFailsWith<JobBuildException> { MarlinWriter().write(Document()) }
    }

    @Test fun `grayscale image merges equal pixels and scales power`() {
        val layers = Document.defaultLayers()
        val img = layers[0].copy(intervalMm = 1.0, powerPct = 100.0, minPowerPct = 0.0, overscanMm = 0.0)
        // 4x2 image: black black white gray / all white
        val raster = Raster.of(4, 2, byteArrayOf(0, 0, 255.toByte(), 128.toByte(), -1, -1, -1, -1))
        val e = Element(layerId = img.id, kind = "Bild", transform = Transform(70.0, 70.0), raster = raster,
                        imageWidthMm = 4.0, imageHeightMm = 2.0)
        val g = MarlinWriter().write(doc(e, layers = listOf(img)))
        assertPiCompatible(g)
        assertTrue("G1 X298.000 Y70.500 F3000 S255" in g, g)    // two black pixels merged, column 0 at big machine X
        assertTrue("G1 X296.000 Y70.500 F3000 S127" in g, g)    // gray pixel at half power
        assertTrue(g.lines().none { it.contains("Y71.500") && Regex("S[1-9]").containsMatchIn(it) }, "white row is skipped")
        val rotated = e.copy(transform = e.transform.copy(rotation = 10.0))
        assertFailsWith<JobBuildException> { MarlinWriter().write(doc(rotated, layers = listOf(img))) }
    }

    @Test fun `material depth per pass derives passes`() {
        assertEquals(2, Document.passesFor(3.0, 1.5))
        assertEquals(3, Document.passesFor(3.0, 1.2))
        assertEquals(1, Document.passesFor(3.0, 0.0))
        val m = Material(name = "Sperrholz", thicknessMm = 4.0, process = "Schneiden", mode = LayerMode.LINE,
                         powerPct = 90.0, speed = 300.0, depthPerPassMm = 1.0, zStepMm = 2.0)
        val layer = m.applyTo(Document.defaultLayers()[2])
        assertEquals(4, layer.passes)
        assertTrue(layer.focusDropMm <= Limits.MAX_FOCUS_DROP_MM + 1e-9, "z step capped to 3 mm total")
    }

    @Test fun `document survives JSON round trip`() {
        val layers = Document.defaultLayers()
        val d = doc(rect(layers[1], 50.0, 50.0).copy(groupId = "g1"), layers = layers)
        assertEquals(d, Document.fromJson(d.toJson()))
    }
}

class SvgImportTest {
    @Test fun `mm document with rect, path and transform`() {
        val svg = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 200 100">
            <rect x="10" y="10" width="20" height="10"/>
            <g transform="translate(100,0)"><path d="M0 0 L20 0 l0 20 z"/></g>
            <circle cx="50" cy="50" r="10" style="display:none"/>
            <text x="0" y="0">ignored</text></svg>"""
        val polys = SvgImport.parse(svg.toByteArray())
        assertEquals(2, polys.size)
        assertEquals(Box(5.0, 5.0, 15.0, 10.0), boundsOf(listOf(polys[0])))
        val tri = boundsOf(listOf(polys[1]))!!
        assertEquals(50.0, tri.minX, 1e-9); assertEquals(60.0, tri.maxX, 1e-9); assertEquals(10.0, tri.maxY, 1e-9)
        assertTrue(polys[1].isClosed())
    }

    @Test fun `curves and arcs are flattened accurately`() {
        val half = SvgImport.pathData("M0 0 A10 10 0 0 1 20 0").first()
        assertEquals(PI * 10, half.length(), 0.05)
        val bez = SvgImport.pathData("M0 0 C0 10 10 10 10 0 S20 -10 20 0").first()
        assertEquals(Pt(20.0, 0.0), bez.last())
        val rel = SvgImport.pathData("m10 10 h5 v5 h-5 z").first()
        assertEquals(Box(10.0, 10.0, 15.0, 15.0), boundsOf(listOf(rel)))
    }

    @Test fun `DOCTYPE and entities are refused`() {
        val evil = """<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg><text>&x;</text></svg>"""
        assertFailsWith<SvgException> { SvgImport.parse(evil.toByteArray()) }
    }
}

class GeometryTest {
    @Test fun `hatch alternates direction and respects holes`() {
        val outer = Shapes.rect(10.0, 10.0)
        val hole = Shapes.rect(4.0, 4.0).map { Pt(it.x + 3, it.y + 3) }
        val rows = hatch(listOf(outer, hole), 1.0)
        val mid = rows.filter { abs(it.first().y - 5.5) < 1e-9 }
        assertEquals(2, mid.size)                                 // split by the hole
        assertTrue(rows[0].first().x < rows[0].last().x)
        assertTrue(rows.last().first().x > rows.last().last().x || rows.size % 2 == 1)
    }

    @Test fun `ordering and simplification`() {
        val a = listOf(Pt(100.0, 0.0), Pt(110.0, 0.0))
        val b = listOf(Pt(20.0, 0.0), Pt(10.0, 0.0))
        val ordered = orderPaths(listOf(a, b))
        assertEquals(Pt(10.0, 0.0), ordered[0].first())           // b reversed, nearest first
        val line = (0..100).map { Pt(it.toDouble(), 0.0) }
        assertEquals(2, simplify(line, 0.01).size)
    }

    @Test fun `homography maps photo corners to the work area`() {
        val photo = listOf(Pt(100.0, 80.0), Pt(1900.0, 120.0), Pt(1850.0, 1400.0), Pt(140.0, 1350.0))
        val bed = listOf(Pt(30.0, 30.0), Pt(390.0, 30.0), Pt(390.0, 370.0), Pt(30.0, 370.0))
        val h = Homography.fit(photo, bed)
        for (i in 0 until 4) { val p = h.map(photo[i]); assertEquals(bed[i].x, p.x, 1e-6); assertEquals(bed[i].y, p.y, 1e-6) }
        val back = Homography.fit(bed, photo)
        val (img, w, ht) = Homography.rectify(IntArray(4) { -1 }, 2, 2, back, 0.1)
        assertEquals(37 * 36, img.size); assertEquals(37, w); assertEquals(36, ht)
        assertFailsWith<IllegalArgumentException> { Homography.fit(List(4) { Pt(it.toDouble(), it.toDouble()) }, bed) }
    }
}

class WorkCoordinatesTest {
    @Test fun `conversion is a 180 degree turn and round trips`() {
        assertEquals(Pt(370.0, 0.0), Work.toMachine(Pt(0.0, 0.0)))         // screen top-left = machine X end, Y 0
        assertEquals(Pt(0.0, 360.0), Work.toMachine(Pt(Work.WIDTH, Work.HEIGHT)))
        assertEquals(Box(292.0, 0.0, 370.0, 35.0), Work.park)              // park corner top right on screen
        val p = Pt(123.4, 56.7)
        Work.fromMachine(Work.toMachine(p)).let { assertEquals(p.x, it.x, 1e-9); assertEquals(p.y, it.y, 1e-9) }
        assertTrue(Work.toMachine(Pt(0.0, 0.0)).let { Bed.inWorkArea(it.x, it.y) })
        assertTrue(Work.toMachine(Pt(Work.WIDTH, Work.HEIGHT)).let { Bed.inWorkArea(it.x, it.y) })
    }

    @Test fun `letter F is not mirrored`() {
        val layers = Document.defaultLayers()
        val cut = layers[2].copy(passes = 1, zStepMm = 0.0)
        // F on screen: stem at the left (x 100), bar and middle bar to the right.
        val f = listOf(listOf(Pt(0.0, 40.0), Pt(0.0, 0.0), Pt(20.0, 0.0)), listOf(Pt(0.0, 20.0), Pt(15.0, 20.0)))
        val e = Element(layerId = cut.id, kind = "F", transform = Transform(100.0, 100.0), paths = f)
        val g = MarlinWriter().write(Document(title = "F", layers = listOf(cut), elements = listOf(e)))
        val t = Toolpath.parse(g)
        val bar = t.segments.filter { it.cut }.maxByOrNull { kotlin.math.abs(it.x1 - it.x0) }!!
        val stemX = minOf(bar.x0, bar.x1).let { _ -> maxOf(bar.x0, bar.x1) }
        val endX = minOf(bar.x0, bar.x1)
        assertEquals(270.0, stemX.toDouble(), 1e-3)      // left on screen = large machine X
        assertEquals(250.0, endX.toDouble(), 1e-3)       // the arm points to small X (screen right)
    }
}
