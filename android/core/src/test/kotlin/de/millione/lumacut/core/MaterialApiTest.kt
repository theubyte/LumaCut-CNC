package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class MaterialApiTest {
    private val sample = """{"revision": 7, "materials": [
        {"id":"a1","name":"Pappel-Sperrholz","thickness_mm":3.0,"process":"Schneiden","mode":"line","power_pct":80.0,
         "speed_mm_min":400.0,"passes":2,"interval_mm":0.1,"depth_per_pass_mm":1.5,"z_step_mm":0.5,"builtin":true,"updated":"2026-10-26T15:00:00Z"},
        {"id":"a2","name":"Pappel-Sperrholz","thickness_mm":3.0,"process":"Gravieren","mode":"fill","power_pct":25.0,
         "speed_mm_min":3000.0,"passes":1,"interval_mm":0.1,"depth_per_pass_mm":0.0,"z_step_mm":0.0,"builtin":true,"unknown":1}]}"""

    @Test fun `list is parsed and grouped by material`() = runBlocking {
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody(sample)); start() }
        val list = PiClient("127.0.0.1", srv.port).materials()
        assertEquals(7, list.revision)
        val mats = list.materials.map { it.toMaterial() }
        assertEquals(LayerMode.LINE, mats[0].mode); assertEquals(LayerMode.FILL, mats[1].mode)
        assertEquals(400.0, mats[0].speed)
        val groups = mats.grouped()
        assertEquals(1, groups.size)
        assertEquals(listOf("Schneiden", "Gravieren"), groups[0].processes)
        assertEquals(25.0, groups[0].entry("gravieren")!!.powerPct)
        assertEquals(1, mats.grouped("sperr").size); assertEquals(0, mats.grouped("acryl").size)
        srv.shutdown()
    }

    @Test fun `create sends json with base_revision and no id, 409 means reload`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"revision":8,"material":{"id":"n1","name":"Filz","thickness_mm":2.0,"process":"Schneiden","mode":"line","power_pct":60.0,"speed_mm_min":900.0}}"""))
            enqueue(MockResponse().setResponseCode(409).setBody("""{"error":"veraltet","revision":9}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        val m = Material(name = "Filz", thicknessMm = 2.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 60.0, speed = 900.0)
        val (rev, stored) = pi.createMaterial(m, 7)
        assertEquals(8, rev); assertEquals("n1", stored.id)
        val req = srv.takeRequest()
        assertEquals("POST", req.method); assertEquals("/api/materials", req.path)
        val body = req.body.readUtf8()
        assertTrue("\"base_revision\":7" in body && "\"power_pct\":60.0" in body && "\"thickness_mm\":2.0" in body, body)
        assertTrue("\"id\"" !in body && "builtin" !in body, body)
        val e = assertFailsWith<PiConflictException> { pi.updateMaterial(stored, 7) }
        assertEquals(9, e.revision)
        val put = srv.takeRequest()
        assertEquals("PUT", put.method); assertEquals("/api/materials/n1", put.path)
        srv.shutdown()
    }

    @Test fun `delete carries the revision, autorun posts the job name`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"revision":10}"""))
            enqueue(MockResponse().setBody("""{"message":"Automatischer Ablauf gestartet"}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        assertEquals(10, pi.deleteMaterial("n1", 9))
        val del = srv.takeRequest()
        assertEquals("DELETE", del.method); assertEquals("/api/materials/n1?base_revision=9", del.path)
        pi.autorun("Schild.gcode")
        assertEquals("op=autorun&name=Schild.gcode", srv.takeRequest().body.readUtf8())
        srv.shutdown()
    }

    @Test fun `light posts on, brightness and effects, status reports dimming`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"message":"Licht EIN · 60 %","lights":true,"brightness":60,"dimmable":true}"""))
            enqueue(MockResponse().setBody("""{"message":"ok"}"""))
            enqueue(MockResponse().setBody("""{"connected":true,"lights":true,"light_brightness":60,"light_dimmable":false,"light_effects":false}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        pi.light(on = true, brightness = 250)
        assertEquals("op=light&on=1&brightness=100", srv.takeRequest().body.readUtf8())
        pi.light(effects = false)
        assertEquals("op=light&effects=0", srv.takeRequest().body.readUtf8())
        val s = pi.status()
        assertEquals(60, s.light_brightness); assertEquals(false, s.light_dimmable); assertEquals(false, s.light_effects)
        srv.shutdown()
    }

    @Test fun `phase and coordinate convention are read, missing means old Pi`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"connected":true,"coord_convention":"origin_top_right","job":{"state":"running","line":50,"total":50,"phase":"finishing"}}"""))
            enqueue(MockResponse().setBody("""{"connected":true,"job":{"state":"running","line":10,"total":50}}"""))
            enqueue(MockResponse().setBody("""{"connected":true,"coord_convention":"origin_bottom_left","job":{"state":"probing","phase":null}}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        val a = pi.status()
        assertTrue(a.coordOk); assertEquals("finishing", a.job.step); assertTrue(a.job.lastPaths)
        val b = pi.status()
        assertTrue(!b.coordOk); assertEquals("running", b.job.step); assertTrue(!b.job.lastPaths)
        val c = pi.status()
        assertTrue(!c.coordOk); assertEquals("probing", c.job.step)
        srv.shutdown()
    }

    @Test fun `job progress carries probe done and total`() = runBlocking {
        val body = """{"connected":true,"job":{"file":"a.gcode","state":"probing","line":0,"total":200,"probe":{"done":3,"total":12}},"features":["autorun_mesh","materials"]}"""
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody(body)); start() }
        val s = PiClient("127.0.0.1", srv.port).status()
        assertTrue(s.job.active); assertEquals(3, s.job.probe.done); assertEquals(12, s.job.probe.total)
        assertTrue("autorun_mesh" in s.features)
        srv.shutdown()
    }
}
