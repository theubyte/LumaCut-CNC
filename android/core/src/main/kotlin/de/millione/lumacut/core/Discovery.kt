package de.millione.lumacut.core

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/** A LumaCut Pi found in the network. [state] is "bereit", "belegt" or "Auftrag läuft". */
data class DiscoveredLaser(val host: String, val port: Int, val name: String, val state: String)

/** Finds the laser's Pi in the local network: /24 around the tablet's address, GET /api/status on port 8080. */
object LaserDiscovery {
    private val json = Json { ignoreUnknownKeys = true }

    /** All other addresses of the /24 around [ip] (no network, broadcast or own address). Local IPv4 only. */
    fun subnetHosts(ip: String): List<String> {
        require(PiClient.isLocalIpv4(ip)) { "Nur lokale IPv4-Adressen" }
        val p = ip.split(".")
        val base = p.take(3).joinToString(".")
        return (1..254).map { "$base.$it" }.filter { it != ip }
    }

    /** True only for the answer of a LumaCut Pi, so other devices on port 8080 never show up. */
    fun parseStatus(body: String, host: String, port: Int = 8080): DiscoveredLaser? {
        val o = try { json.parseToJsonElement(body) as? JsonObject } catch (e: Exception) { null } ?: return null
        val features = (o["features"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
        val hasJob = o["job"] is JsonObject
        val ours = "autorun_mesh" in features || "materials" in features ||
            (o.containsKey("coord_convention") && hasJob) ||
            (o["firmware"]?.let { (it as? JsonPrimitive)?.contentOrNull } == "marlin" && hasJob && o.containsKey("connected"))
        if (!ours) return null
        val identity = (o["identity"] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }
        // the name the owner gave the Pi (web UI Einstellungen → Gerät); older Pis have none
        val machineName = ((o["config"] as? JsonObject)?.get("machine_name") as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }
        val connected = (o["connected"] as? JsonPrimitive)?.booleanOrNull ?: false
        val owner = (o["owner"] as? JsonPrimitive)?.contentOrNull ?: "Frei"
        val state = (o["job"] as? JsonObject)?.get("state")?.let { (it as? JsonPrimitive)?.contentOrNull }
        val busy = state in setOf("homing", "probing", "running")
        return DiscoveredLaser(host, port, machineName ?: identity ?: "LumaCut-Laser", when {
            busy -> "Auftrag läuft"
            !connected -> "Controller getrennt"
            owner != "Frei" && owner.isNotBlank() -> "belegt"
            else -> "bereit"
        })
    }

    fun fastClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(900, TimeUnit.MILLISECONDS).readTimeout(1200, TimeUnit.MILLISECONDS).callTimeout(1500, TimeUnit.MILLISECONDS)
        .retryOnConnectionFailure(false).build()

    fun probe(host: String, port: Int, http: OkHttpClient): DiscoveredLaser? = try {
        val req = Request.Builder().url("http://$host:$port/api/status").build()
        http.newCall(req).execute().use { r -> if (r.isSuccessful) parseStatus(r.body?.string().orEmpty(), host, port) else null }
    } catch (e: Exception) { null }

    /** Probes all [candidates] in parallel and returns the Pis that answered within about [timeoutMs]. */
    @OptIn(ExperimentalCoroutinesApi::class)
    suspend fun scanHosts(candidates: List<Pair<String, Int>>, timeoutMs: Long = 3000, http: OkHttpClient = fastClient(),
                          dispatcher: CoroutineDispatcher = Dispatchers.IO.limitedParallelism(128)): List<DiscoveredLaser> = coroutineScope {
        val found = java.util.Collections.synchronizedList(ArrayList<DiscoveredLaser>())
        val jobs = candidates.filter { PiClient.isLocalIpv4(it.first) }.map { (h, p) -> launch(dispatcher) { probe(h, p, http)?.let { found += it } } }
        withTimeoutOrNull(timeoutMs) { jobs.joinAll() }
        jobs.forEach { it.cancel() }
        found.toList().sortedBy { host -> host.host.split(".").last().toIntOrNull() ?: 0 }
    }

    suspend fun scan(localIp: String, timeoutMs: Long = 3000): List<DiscoveredLaser> =
        scanHosts(subnetHosts(localIp).map { it to 8080 }, timeoutMs)
}
