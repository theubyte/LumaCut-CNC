package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import java.io.File
import java.security.MessageDigest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AppUpdateTest {
    private val apk = ByteArray(200_000) { (it * 31).toByte() }
    private val sha = MessageDigest.getInstance("SHA-256").digest(apk).joinToString("") { "%02x".format(it) }
    private fun meta() =
        """{"available":true,"version_code":42,"version_name":"1.0.42","sha256":"$sha","size":${apk.size},"checked_at":"2026-10-27T08:00:00Z","error":null}"""

    @Test fun `metadata is read and compared with the installed version`() = runBlocking {
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody(meta())); start() }
        val info = PiClient("127.0.0.1", srv.port).appUpdate()
        assertEquals("/api/app/android", srv.takeRequest().path)
        assertEquals("1.0.42", info.version_name)
        assertTrue(info.isNewerThan(41)); assertFalse(info.isNewerThan(42)); assertFalse(info.isNewerThan(50))
        assertFalse(AppUpdateInfo(available = false, version_code = 99).isNewerThan(1))
        srv.shutdown()
    }

    @Test fun `check posts app_update_check and reads the answer`() = runBlocking {
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody("""{"message":"Geprüft",""" + meta().drop(1))); start() }
        val info = PiClient("127.0.0.1", srv.port).appUpdateCheck()
        assertEquals("op=app_update_check", srv.takeRequest().body.readUtf8())
        assertEquals(42, info.version_code)
        srv.shutdown()
    }

    @Test fun `download is verified and reports progress`() = runBlocking {
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody(Buffer().write(apk))); start() }
        val dir = createTempDir("apk"); val dest = File(dir, "update.apk")
        var last = 0L
        val info = AppUpdateInfo(true, 42, "1.0.42", sha.uppercase(), apk.size.toLong())
        val f = PiClient("127.0.0.1", srv.port).downloadApp(info, dest) { n, _ -> last = n }
        assertEquals("/api/app/android.apk", srv.takeRequest().path)
        assertTrue(f.readBytes().contentEquals(apk)); assertEquals(apk.size.toLong(), last)
        srv.shutdown(); dir.deleteRecursively()
    }

    @Test fun `wrong checksum or size discards the file`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody(Buffer().write(apk)))
            enqueue(MockResponse().setBody(Buffer().write(apk.copyOf(1000))))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        val dir = createTempDir("apk"); val dest = File(dir, "update.apk")
        assertFailsWith<PiException> { pi.downloadApp(AppUpdateInfo(true, 42, "x", "00".repeat(32), apk.size.toLong()), dest) }
        assertFailsWith<PiException> { pi.downloadApp(AppUpdateInfo(true, 42, "x", sha, apk.size.toLong()), dest) }
        assertFalse(dest.exists()); assertEquals(0, dir.listFiles()!!.size)
        assertFailsWith<PiException> { pi.downloadApp(AppUpdateInfo(true, 42, "x", "", 1), dest) }
        srv.shutdown(); dir.deleteRecursively()
    }
}
