package de.millione.lumacut.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.FormBody
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Automatic height probing of the Pi (job.probe in /api/status): [done] of [total] points. */
@Serializable
data class ProbeProgress(val done: Int = 0, val total: Int = 0)

@Serializable
data class JobProgress(val file: String = "", val state: String = "idle", val line: Int = 0,
                       val total: Int = 0, val error: String = "", val probe: ProbeProgress = ProbeProgress()) {
    val active get() = state in setOf("homing", "probing", "running")
    val fraction get() = if (total > 0) line.toDouble() / total else 0.0
}

/** Laser-off outline run (op=frame). */
@Serializable
data class FrameProgress(val state: String = "idle", val mode: String = "", val line: Int = 0,
                         val total: Int = 0, val error: String = "") {
    val active get() = state == "running"
}

@Serializable
data class FirmwareUpdate(val state: String = "idle", val progress: Int = 0, val message: String = "")

@Serializable
data class PiConfig(
    val validated: Boolean = false,
    val z_clearance_mm: Double = 20.0,
    val focus_gap_mm: Double = 7.0,
    val z_switch_tip_offset_mm: Double = 1.5,
    val probe_offset_x_mm: Double? = null,
    val probe_offset_y_mm: Double? = null,
)

/** Mirror of the Pi's /api/status (pi400/marlin/web.py). Unknown keys are ignored. */
@Serializable
data class MachineStatus(
    val connected: Boolean = false,
    val state: String = "Disconnected",
    val owner: String = "Frei",
    val identity: String = "",
    val homed: Boolean = false,
    val emergency_latched: Boolean = false,
    val position: List<Double>? = null,
    val fault: String = "",
    val lights: Boolean = false,
    val exhaust: Boolean = false,
    val laser_cooling_fan_on: Boolean = false,
    val cooldown_remaining_s: Int? = null,
    val workpiece_surface_z: Double? = null,
    val laser_focus_z: Double? = null,
    val probe_xy_offset_mm: List<Double>? = null,
    val firmware_upload_supported: Boolean = false,
    val firmware_update: FirmwareUpdate = FirmwareUpdate(),
    val job: JobProgress = JobProgress(),
    val frame: FrameProgress = FrameProgress(),
    val config: PiConfig = PiConfig(),
    val camera: CameraInfo = CameraInfo(),
    val recent: List<String> = emptyList(),
) {
    val ownerFree get() = owner == "Frei" || owner.isBlank()
    val probeOffset: Pt? get() = probe_xy_offset_mm?.takeIf { it.size == 2 }?.let { Pt(it[0], it[1]) }
}

@Serializable
data class CameraInfo(val device: String = "", val available: Boolean = false)

@Serializable
data class JobFile(val name: String, val bytes: Long = 0, val modified: Long = 0)

@Serializable
private data class JobList(val files: List<JobFile> = emptyList())

open class PiException(message: String) : IOException(message)

/**
 * HTTP client for the Pi 400 service on port 8080. All safety rules are
 * enforced by the Pi; this class only transports requests.
 */
class PiClient(
    val host: String,
    private val port: Int = 8080,
    private val http: OkHttpClient = defaultClient(),
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false }
    private val bodyJson = Json { encodeDefaults = true; explicitNulls = false }

    init {
        require(isLocalIpv4(host)) { "Nur lokale IPv4-Adressen (z. B. 192.168.2.89)" }
    }

    private fun url(vararg segments: String): HttpUrl =
        HttpUrl.Builder().scheme("http").host(host).port(port).apply { segments.forEach { addPathSegment(it) } }.build()

    private suspend fun call(request: Request, longRunning: Boolean = false): String = withContext(Dispatchers.IO) {
        val client = if (longRunning) http.newBuilder().readTimeout(300, TimeUnit.SECONDS).build() else http
        try {
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (response.code == 409) throw PiConflictException(errorText(body) ?: "Die Liste wurde inzwischen geändert", revisionOf(body))
                if (!response.isSuccessful) throw PiException(errorText(body) ?: "Pi antwortet mit HTTP ${response.code}")
                body
            }
        } catch (e: PiException) {
            throw e
        } catch (e: IOException) {
            throw PiException("Pi nicht erreichbar (${e.message ?: e.javaClass.simpleName})")
        }
    }

    private fun errorText(body: String): String? = runCatching {
        json.parseToJsonElement(body).jsonObject["error"]?.jsonPrimitive?.content
    }.getOrNull()

    private fun revisionOf(body: String): Int? = runCatching {
        json.parseToJsonElement(body).jsonObject["revision"]?.jsonPrimitive?.content?.toInt()
    }.getOrNull()

    private fun message(body: String): String = runCatching {
        json.parseToJsonElement(body).jsonObject["message"]?.jsonPrimitive?.content
    }.getOrNull() ?: "Erledigt"

    suspend fun status(): MachineStatus =
        json.decodeFromString(MachineStatus.serializer(), call(Request.Builder().url(url("api", "status")).build()))

    suspend fun jobs(): List<JobFile> =
        json.decodeFromString(JobList.serializer(), call(Request.Builder().url(url("api", "jobs")).build())).files

    suspend fun jobContent(name: String): String =
        call(Request.Builder().url(url("api", "jobs", checkJobName(name), "content")).build())

    suspend fun deleteJob(name: String): String =
        message(call(Request.Builder().url(url("api", "jobs", checkJobName(name), "delete")).post(FormBody.Builder().build()).build()))

    /** /api/action with op and fields; homing, probing and parking wait for the machine. */
    suspend fun action(op: String, fields: Map<String, String> = emptyMap()): String {
        require(op in ACTIONS) { "Aktion nicht vorgesehen: $op" }
        val form = FormBody.Builder().add("op", op).apply { fields.forEach { (k, v) -> add(k, v) } }.build()
        val long = op in setOf("home", "probe", "park", "moveto")
        return message(call(Request.Builder().url(url("api", "action")).post(form).build(), longRunning = long))
    }

    /**
     * Starts the automatic run for an uploaded job: the Pi homes if needed, probes the
     * surface, corrects the height, lasers and parks (docs/ZUSAMMENARBEIT_CLAUDE_GROK.md section 4).
     */
    suspend fun autorun(name: String): String = action("autorun", mapOf("name" to checkJobName(name)))

    /* ---------- material database (/api/materials) ---------- */

    suspend fun materials(): MaterialList =
        json.decodeFromString(MaterialList.serializer(), call(Request.Builder().url(url("api", "materials")).build()))

    /** Adds [m] as a new entry; returns the new revision and the stored material. */
    suspend fun createMaterial(m: Material, baseRevision: Int): Pair<Int, Material> =
        materialWrite(Request.Builder().url(url("api", "materials")).post(materialBody(m.toPi(newEntry = true), baseRevision)).build())

    suspend fun updateMaterial(m: Material, baseRevision: Int): Pair<Int, Material> =
        materialWrite(Request.Builder().url(url("api", "materials", m.id)).put(materialBody(m.toPi(), baseRevision)).build())

    /** Returns the new revision. */
    suspend fun deleteMaterial(id: String, baseRevision: Int): Int {
        val u = url("api", "materials", id).newBuilder().addQueryParameter("base_revision", baseRevision.toString()).build()
        return revisionOf(call(Request.Builder().url(u).delete().build())) ?: baseRevision + 1
    }

    private fun materialBody(m: PiMaterial, baseRevision: Int): RequestBody {
        val obj = buildJsonObject {
            val fields = bodyJson.encodeToJsonElement(PiMaterial.serializer(), m).jsonObject
            for ((k, v) in fields) if (k != "builtin" && k != "updated") put(k, v)
            put("base_revision", baseRevision)
        }
        return obj.toString().toRequestBody("application/json".toMediaType())
    }

    private suspend fun materialWrite(request: Request): Pair<Int, Material> {
        val root = json.parseToJsonElement(call(request)).jsonObject
        val stored = json.decodeFromJsonElement(PiMaterial.serializer(), root.getValue("material")).toMaterial()
        return (root["revision"]?.jsonPrimitive?.content?.toInt() ?: 0) to stored
    }

    /** Traces [program] (from [Frame.program]) with the laser off. */
    suspend fun frame(program: String, mode: Frame.Mode): String = action("frame", mapOf("gcode" to program, "mode" to mode.api))

    /** Laser-off move of the head to machine X/Y; Z only goes up (camera scan). */
    suspend fun moveTo(machineX: Double, machineY: Double): String = action("moveto", mapOf(
        "x" to "%.3f".format(java.util.Locale.ROOT, machineX), "y" to "%.3f".format(java.util.Locale.ROOT, machineY)))

    /** JPEG from the head camera on the Pi. */
    suspend fun cameraSnapshot(width: Int = 1280, height: Int = 720): ByteArray = withContext(Dispatchers.IO) {
        val u = url("api", "camera", "snapshot").newBuilder()
            .addQueryParameter("w", width.toString()).addQueryParameter("h", height.toString()).build()
        try {
            http.newBuilder().readTimeout(20, TimeUnit.SECONDS).build().newCall(Request.Builder().url(u).build()).execute().use { r ->
                val bytes = r.body?.bytes() ?: ByteArray(0)
                if (!r.isSuccessful) throw PiException(errorText(bytes.toString(Charsets.UTF_8)) ?: "Kamera: HTTP ${r.code}")
                if (bytes.size < 2 || bytes[0] != 0xFF.toByte() || bytes[1] != 0xD8.toByte()) throw PiException("Kamera liefert kein JPEG")
                bytes
            }
        } catch (e: PiException) { throw e } catch (e: IOException) { throw PiException("Pi nicht erreichbar (${e.message ?: e.javaClass.simpleName})") }
    }

    suspend fun settings(values: Map<String, String>): String {
        val form = FormBody.Builder().apply { values.forEach { (k, v) -> add(k, v) } }.build()
        return message(call(Request.Builder().url(url("api", "settings")).post(form).build()))
    }

    suspend fun uploadJob(name: String, gcode: String): String = upload("upload", checkJobName(name), gcode.toByteArray())

    suspend fun uploadFirmware(name: String, image: ByteArray): String {
        require(image.size in 32 * 1024..256 * 1024) { "Firmware-Datei hat eine unplausible Größe" }
        return upload("firmware", if (name.endsWith(".bin", true)) name else "firmware.bin", image)
    }

    private suspend fun upload(endpoint: String, name: String, data: ByteArray): String {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", name, data.toRequestBody("application/octet-stream".toMediaType()))
            .build()
        return message(call(Request.Builder().url(url("api", endpoint)).post(body).build(), longRunning = true))
    }

    companion object {
        val ACTIONS = setOf("home", "jog", "probe", "park", "light", "exhaust", "start", "autorun", "frame", "moveto",
                            "abort", "estop", "estop_reset")

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()

        fun isLocalIpv4(host: String): Boolean {
            val parts = host.split(".")
            if (parts.size != 4) return false
            val n = parts.map { it.toIntOrNull() ?: return false }
            if (n.any { it !in 0..255 }) return false
            return n[0] == 10 || n[0] == 127 || (n[0] == 192 && n[1] == 168) || (n[0] == 172 && n[1] in 16..31)
        }

        private val JOB_NAME = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\\.(gcode|gc|nc)$", RegexOption.IGNORE_CASE)

        fun checkJobName(name: String): String {
            require(JOB_NAME.matches(name)) { "Auftragsname: nur A–Z, 0–9, - _ . und Endung .gcode" }
            return name
        }

        /** Turns a free text title into a valid job file name. */
        fun jobNameFrom(title: String): String {
            val base = title.trim()
                .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
                .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
                .replace(Regex("[^A-Za-z0-9._-]+"), "-").trim('-', '.').take(60)
            return (base.ifEmpty { "auftrag" }) + ".gcode"
        }
    }
}
