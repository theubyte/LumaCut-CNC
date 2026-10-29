package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class SavedProjectsTest {
    @Test fun `list, open, save and delete talk to api projects`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"projects":[{"id":"a1","name":"Maxim Einladung","bytes":1200,
                "updated_at":"2026-10-29T21:04:42Z","updated_by":"SM-T733","elements":2,"layers":2,"plates":1,"extra":1}]}"""))
            enqueue(MockResponse().setBody("""{"title":"Maxim","layers":[],"elements":[]}"""))
            enqueue(MockResponse().setBody("""{"project":{"id":"a1","name":"Maxim Einladung","elements":0,"replaced":true}}"""))
            enqueue(MockResponse().setBody("""{"message":"Projekt gelöscht"}"""))
            enqueue(MockResponse().setResponseCode(404).setBody("""{"error":"Projekt nicht gefunden"}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        val list = pi.savedProjects()
        assertEquals("Maxim Einladung", list.single().name)
        assertEquals("29.10.2026 22:04 · SM-T733 · 2 Elemente", SavedProjects.line(list.single(), ZoneId.of("Europe/Berlin")))
        assertEquals("GET /api/projects", srv.takeRequest().requestLine.substringBeforeLast(" "))

        assertTrue(pi.savedProject("a1").contains("\"Maxim\""))
        assertEquals("/api/projects/a1", srv.takeRequest().path)

        val saved = pi.saveProjectAs(" maxim einladung ", """{"layers":[],"elements":[]}""", "Tablet")
        assertTrue(saved.replaced)
        val post = srv.takeRequest()
        assertEquals("POST", post.method)
        assertEquals("/api/projects?name=maxim%20einladung&by=Tablet", post.path)
        assertEquals("""{"layers":[],"elements":[]}""", post.body.readUtf8())

        assertEquals("Projekt gelöscht", pi.deleteSavedProject("a1"))
        assertEquals("DELETE", srv.takeRequest().method)
        val e = assertFailsWith<PiException> { pi.savedProject("weg") }
        assertEquals("Projekt nicht gefunden", e.message)
        srv.shutdown()
    }

    @Test fun `same name ignores case and extra spaces`() {
        val list = listOf(SavedProject("1", "Maxim Einladung"), SavedProject("2", "Schild"))
        assertEquals("1", SavedProjects.named(list, "  maxim   EINLADUNG ")?.id)
        assertEquals(null, SavedProjects.named(list, "Maxim"))
        assertEquals("1 Element", SavedProjects.line(SavedProject("3", "x", elements = 1)))
    }
}
