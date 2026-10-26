package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.RecordedRequest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PartSplitterTest {
    private fun square(x: Double, y: Double, s: Double): Poly = Shapes.rect(s, s).map { Pt(it.x + x, it.y + y) }

    @Test fun `two separate squares are two parts`() {
        val r = PartSplitter.split(listOf(square(0.0, 0.0, 10.0), square(30.0, 0.0, 10.0)))
        assertEquals(2, r.parts.size); assertTrue(r.parts.all { it.size == 1 }); assertTrue(!r.tooMany)
    }

    @Test fun `square with a hole is one part with two paths`() {
        val r = PartSplitter.split(listOf(square(0.0, 0.0, 30.0), square(10.0, 10.0, 10.0)))
        assertEquals(1, r.parts.size); assertEquals(2, r.parts[0].size)
    }

    @Test fun `ring inside the hole of a square is its own part`() {
        val r = PartSplitter.split(listOf(square(0.0, 0.0, 60.0), square(10.0, 10.0, 40.0), square(20.0, 20.0, 20.0), square(25.0, 25.0, 10.0)))
        assertEquals(2, r.parts.size)
        assertEquals(setOf(2), r.parts.map { it.size }.toSet())
        val outer = boundsOf(r.parts[0])!!; assertEquals(60.0, outer.width, 1e-9)
        val ring = boundsOf(r.parts[1])!!; assertEquals(20.0, ring.width, 1e-9)
    }

    @Test fun `open paths and text-like shapes`() {
        val open = listOf(Pt(0.0, 0.0), Pt(10.0, 0.0), Pt(10.0, 5.0))
        val r = PartSplitter.split(listOf(open, square(20.0, 0.0, 5.0), open.map { Pt(it.x, it.y + 30) }))
        assertEquals(3, r.parts.size)
        // letter O: ellipse with an inner ellipse stays one part
        val o = PartSplitter.split(listOf(Shapes.ellipse(20.0, 30.0), Shapes.ellipse(8.0, 18.0).map { Pt(it.x + 6, it.y + 6) }))
        assertEquals(1, o.parts.size)
    }

    @Test fun `very many parts stay one element`() {
        val many = (0 until 600).map { square((it % 30) * 12.0, (it / 30) * 12.0, 10.0) }
        val r = PartSplitter.split(many)
        assertTrue(r.tooMany); assertEquals(1, r.parts.size); assertEquals(600, r.parts[0].size)
        assertEquals(500, PartSplitter.split(many.take(500)).parts.size)
    }
}

class DiscoveryTest {
    private val status = """{"connected":true,"state":"Idle","owner":"Frei","identity":"LumaCut SKR Mini MZ","firmware":"marlin",
        "coord_convention":"origin_top_right","features":["autorun_mesh","materials"],"job":{"state":"idle"}}"""

    @Test fun `subnet is the 254 other addresses of the 24`() {
        val hosts = LaserDiscovery.subnetHosts("192.168.2.50")
        assertEquals(253, hosts.size)
        assertTrue("192.168.2.89" in hosts && "192.168.2.50" !in hosts && "192.168.2.0" !in hosts && "192.168.2.255" !in hosts)
        assertEquals("192.168.2.1", hosts.first()); assertEquals("192.168.2.254", hosts.last())
        assertFailsWith<IllegalArgumentException> { LaserDiscovery.subnetHosts("8.8.8.8") }
    }

    @Test fun `only the Pi status answer is recognised`() {
        val l = assertNotNull(LaserDiscovery.parseStatus(status, "192.168.2.89"))
        assertEquals("LumaCut SKR Mini MZ", l.name); assertEquals("bereit", l.state); assertEquals("192.168.2.89", l.host)
        assertEquals("belegt", LaserDiscovery.parseStatus(status.replace("\"Frei\"", "\"lightburn\""), "h")!!.state)
        assertEquals("Auftrag läuft", LaserDiscovery.parseStatus(status.replace("\"idle\"", "\"probing\""), "h")!!.state)
        assertEquals("Controller getrennt", LaserDiscovery.parseStatus(status.replace("\"connected\":true", "\"connected\":false"), "h")!!.state)
        // an older Pi without features is still recognised by the convention + job fields
        assertNotNull(LaserDiscovery.parseStatus("""{"connected":true,"coord_convention":"origin_top_right","job":{}}""", "h"))
        // other devices on port 8080
        assertNull(LaserDiscovery.parseStatus("""{"status":"ok","version":"1.2"}""", "h"))
        assertNull(LaserDiscovery.parseStatus("""{"job":{},"connected":true}""", "h"))
        assertNull(LaserDiscovery.parseStatus("<html>Router</html>", "h"))
        assertNull(LaserDiscovery.parseStatus("[1,2,3]", "h"))
    }

    @Test fun `parallel scan finds the Pi and ignores other servers and closed ports`() = runBlocking {
        val pi = MockWebServer().apply { enqueue(MockResponse().setBody(status)); start() }
        val other = MockWebServer().apply {
            dispatcher = object : Dispatcher() { override fun dispatch(request: RecordedRequest) = MockResponse().setBody("""{"hello":"router"}""") }
            start()
        }
        val closed = MockWebServer().apply { start() }.also { it.shutdown() }
        val found = LaserDiscovery.scanHosts(listOf("127.0.0.1" to pi.port, "127.0.0.1" to other.port, "127.0.0.1" to closed.port), timeoutMs = 3000)
        assertEquals(1, found.size)
        assertEquals(pi.port, found[0].port)
        assertEquals("/api/status", pi.takeRequest().path)
        // non-local addresses are never probed
        assertEquals(0, LaserDiscovery.scanHosts(listOf("8.8.8.8" to 8080), timeoutMs = 500).size)
        pi.shutdown(); other.shutdown()
    }
}
