package de.millione.lumacut.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** The APK the Pi offers (GET /api/app/android); [version_code] is compared with the installed versionCode. */
@Serializable
data class AppUpdateInfo(val available: Boolean = false, val version_code: Int = 0, val version_name: String = "",
                         val sha256: String = "", val size: Long = 0, val checked_at: String? = null, val error: String? = null) {
    fun isNewerThan(installedCode: Int) = available && version_code > installedCode
}

/** Automatic height probing of the Pi (job.probe in /api/status): [done] of [total] points. */
@Serializable
data class ProbeProgress(val done: Int = 0, val total: Int = 0)

@Serializable
data class JobProgress(val file: String = "", val state: String = "idle", val line: Int = 0,
                       val total: Int = 0, val error: String = "", val probe: ProbeProgress = ProbeProgress(),
                       val phase: String? = null) {
    /** Finer step while active (homing, probing, focusing, running, finishing, parking); falls back to [state]. */
    val step get() = phase?.takeIf { it.isNotBlank() } ?: state
    /** All lines are sent, the Pi is draining its buffer and parks next; the laser is not off yet. */
    val lastPaths get() = state == "running" && total > 0 && line >= total
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
    /** Fixed head-camera values from the light calibration (Pi with "camera_settings"). */
    val camera: CameraSettings? = null,
    /** Measured X/Y acceleration and speed (motion calibration); null values = firmware. */
    val motion: PiMotion? = null,
)

@Serializable
data class PiMotion(val accel: Double? = null, val speed: Double? = null) {
    val measured get() = accel != null && speed != null
    fun toMotion() = if (accel != null && speed != null) MarlinWriter.Motion(accel, speed) else MarlinWriter.Motion.FIRMWARE
}

/**
 * Fixed head-camera values, each null = automatic: [exposure] in 100 µs
 * (V4L2 exposure_time_absolute), [white_balance] in Kelvin, [light] = LED
 * level in % for scans. [ranges] = what the camera accepts (read only).
 */
@Serializable
data class CameraSettings(
    val exposure: Int? = null,
    val gain: Int? = null,
    val white_balance: Int? = null,
    val light: Int? = null,
    val ranges: Map<String, List<Int>> = emptyMap(),
) {
    fun range(key: String, default: IntRange): IntRange = ranges[key]?.takeIf { it.size == 2 }?.let { it[0]..it[1] } ?: default
}

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
    /** 1..100 %; dimmable null = not yet known, false = old firmware without M355. */
    // Number: older Pi versions sent 60.0, newer send 60 – both must be read.
    val light_brightness: Double? = null,
    val light_dimmable: Boolean? = null,
    val light_effects: Boolean = true,
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
    /** Reference check by the X/Y switches at X0/Y0; [ReferenceInfo.lost] says why the machine is no longer homed. */
    val reference: ReferenceInfo = ReferenceInfo(),
    val camera: CameraInfo = CameraInfo(),
    val recent: List<String> = emptyList(),
    /** Pi capabilities: "autorun_mesh" (op=autorun probes and corrects itself), "materials" (/api/materials). */
    val features: List<String> = emptyList(),
    /** "origin_top_right" = Pi uses the 2026-10-26 axis convention; missing = old Pi. */
    val coord_convention: String? = null,
) {
    val coordOk get() = coord_convention == PiClient.COORD_CONVENTION
    val ownerFree get() = owner == "Frei" || owner.isBlank()
    val probeOffset: Pt? get() = probe_xy_offset_mm?.takeIf { it.size == 2 }?.let { Pt(it[0], it[1]) }
}

/** switch_check: true = the X/Y switches confirm the reference at X0/Y0, false = they cannot, null = not yet homed. */
@Serializable
data class ReferenceInfo(val switch_check: Boolean? = null, val lost: String = "")

@Serializable
data class CameraInfo(val device: String = "", val available: Boolean = false)

@Serializable
data class JobFile(val name: String, val bytes: Long = 0, val modified: Long = 0)

@Serializable
private data class JobList(val files: List<JobFile> = emptyList())

open class PiException(message: String) : IOException(message)

/** The Pi answered, but the status could not be read (app and Pi versions do not match). */
class PiStatusFormatException(message: String) : PiException(message)

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

    private suspend fun call(request: Request, longRunning: Boolean = false, callTimeoutSec: Long = 0): String = withContext(Dispatchers.IO) {
        val client = when {
            longRunning -> http.newBuilder().readTimeout(300, TimeUnit.SECONDS).build()
            callTimeoutSec > 0 -> http.newBuilder().callTimeout(callTimeoutSec, TimeUnit.SECONDS).build()
            else -> http
        }
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

    suspend fun status(): MachineStatus {
        val body = call(Request.Builder().url(url("api", "status")).build(), callTimeoutSec = 5)
        return try {
            json.decodeFromString(MachineStatus.serializer(), body)
        } catch (e: IllegalArgumentException) {   // kotlinx SerializationException
            throw PiStatusFormatException("Antwort des Pi nicht lesbar – App und Pi auf denselben Stand bringen (${e.message?.take(80)})")
        }
    }

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
        val long = op in setOf("home", "probe", "park", "moveto", "motion_test", "motion_limits")
        return message(call(Request.Builder().url(url("api", "action")).post(form).build(), longRunning = long))
    }

    /** Light on PC8: switch and/or dim (1..100 %) and/or effects on/off; absent values stay as they are. */
    suspend fun light(on: Boolean? = null, brightness: Int? = null, effects: Boolean? = null): String {
        val f = linkedMapOf<String, String>()
        on?.let { f["on"] = if (it) "1" else "0" }
        brightness?.let { f["brightness"] = it.coerceIn(1, 100).toString() }
        effects?.let { f["effects"] = if (it) "1" else "0" }
        return action("light", f)
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

    /** Laser-off stress moves at a test acceleration/speed around machine X/Y (motion calibration). */
    suspend fun motionTest(accel: Double, speed: Double, machineX: Double, machineY: Double, span: Double, cycles: Int): String =
        action("motion_test", mapOf("accel" to "%.0f".format(java.util.Locale.ROOT, accel), "speed" to "%.0f".format(java.util.Locale.ROOT, speed),
            "x" to "%.3f".format(java.util.Locale.ROOT, machineX), "y" to "%.3f".format(java.util.Locale.ROOT, machineY),
            "span" to "%.1f".format(java.util.Locale.ROOT, span), "cycles" to cycles.toString()))

    /** Stores the measured limits on the Pi (sent to Marlin now and on every connect); null = firmware values. */
    suspend fun motionLimits(m: MarlinWriter.Motion?): String = action("motion_limits",
        if (m == null) mapOf("accel" to "", "speed" to "")
        else mapOf("accel" to "%.0f".format(java.util.Locale.ROOT, m.accel), "speed" to "%.0f".format(java.util.Locale.ROOT, m.speed)))

    /** Laser-off move of the head to machine X/Y; Z only goes up (camera scan). */
    suspend fun moveTo(machineX: Double, machineY: Double): String = action("moveto", mapOf(
        "x" to "%.3f".format(java.util.Locale.ROOT, machineX), "y" to "%.3f".format(java.util.Locale.ROOT, machineY)))

    /**
     * JPEG from the head camera on the Pi. [whiteBalance] (Kelvin, 0 =
     * automatic) overrides the stored value for this one picture.
     */
    suspend fun cameraSnapshot(width: Int = 1280, height: Int = 720, whiteBalance: Int? = null): ByteArray = withContext(Dispatchers.IO) {
        val u = url("api", "camera", "snapshot").newBuilder()
            .addQueryParameter("w", width.toString()).addQueryParameter("h", height.toString())
            .apply { whiteBalance?.let { addQueryParameter("wb", if (it == 0) "auto" else it.toString()) } }.build()
        try {
            http.newBuilder().readTimeout(20, TimeUnit.SECONDS).build().newCall(Request.Builder().url(u).build()).execute().use { r ->
                val bytes = r.body?.bytes() ?: ByteArray(0)
                if (!r.isSuccessful) throw PiException(errorText(bytes.toString(Charsets.UTF_8)) ?: "Kamera: HTTP ${r.code}")
                if (bytes.size < 2 || bytes[0] != 0xFF.toByte() || bytes[1] != 0xD8.toByte()) throw PiException("Kamera liefert kein JPEG")
                bytes
            }
        } catch (e: PiException) { throw e } catch (e: IOException) { throw PiException("Pi nicht erreichbar (${e.message ?: e.javaClass.simpleName})") }
    }

    suspend fun cameraSettings(): CameraSettings =
        json.decodeFromString(CameraSettings.serializer(), call(Request.Builder().url(url("api", "camera", "settings")).build()))

    /** Stores fixed camera values (null = automatic); the ranges are not sent. */
    suspend fun saveCameraSettings(s: CameraSettings): String {
        val body = buildJsonObject {
            put("exposure", s.exposure?.let(::JsonPrimitive) ?: JsonNull)
            put("gain", s.gain?.let(::JsonPrimitive) ?: JsonNull)
            put("white_balance", s.white_balance?.let(::JsonPrimitive) ?: JsonNull)
            put("light", s.light?.let(::JsonPrimitive) ?: JsonNull)
        }
        return message(call(Request.Builder().url(url("api", "camera", "settings"))
            .put(body.toString().toRequestBody("application/json".toMediaType())).build()))
    }

    /** Head-camera calibration the tablet stored on the Pi (null when there is none) and the file's revision. */
    suspend fun cameraCalibration(): Pair<CameraCalibration?, Int> {
        val root = json.parseToJsonElement(call(Request.Builder().url(url("api", "camera", "calibration")).build())).jsonObject
        val revision = root["revision"]?.jsonPrimitive?.content?.toIntOrNull() ?: 0
        val cal = root["android"]?.takeIf { it is JsonObject }?.let {
            runCatching { Document.JSON.decodeFromJsonElement(CameraCalibration.serializer(), it) }.getOrNull()
        }
        return cal to revision
    }

    /**
     * Stores [cal] on the Pi: the tablet's model unchanged under `android`,
     * plus picture size, scan height and (with a lens model) the OpenCV
     * values in the Pi's own fields. Reads the revision first; if someone
     * saved in between it reads again and saves once more.
     */
    suspend fun saveCameraCalibration(cal: CameraCalibration): String {
        var last: PiConflictException? = null
        repeat(2) {
            val (_, revision) = cameraCalibration()
            val body = buildJsonObject {
                put("revision", revision)
                put("updated_by", "Tablet")
                put("calibrated", true)
                put("image_width", cal.photoWidth)
                put("image_height", cal.photoHeight)
                put("scan_z", cal.scanZ.coerceIn(0.0, Limits.Z_MAX_MM))
                cal.lens?.openCv()?.let { (k, d) ->
                    put("camera_matrix", JsonArray(k.map { row -> JsonArray(row.map(::JsonPrimitive)) }))
                    put("dist_coeffs", JsonArray(d.map(::JsonPrimitive)))
                }
                put("notes", if (cal.lens != null) "Punktraster, Tablet" else "Vier Ecken, Tablet")
                put("android", Document.JSON.encodeToJsonElement(CameraCalibration.serializer(), cal))
            }
            try {
                return message(call(Request.Builder().url(url("api", "camera", "calibration"))
                    .put(body.toString().toRequestBody("application/json".toMediaType())).build()))
            } catch (e: PiConflictException) { last = e }
        }
        throw last!!
    }

    suspend fun appUpdate(): AppUpdateInfo = parseUpdate(call(Request.Builder().url(url("api", "app", "android")).build(), callTimeoutSec = 8))

    /** Asks the Pi to look at GitHub right now; the answer carries the same fields as [appUpdate]. */
    suspend fun appUpdateCheck(): AppUpdateInfo {
        val form = FormBody.Builder().add("op", "app_update_check").build()
        return parseUpdate(call(Request.Builder().url(url("api", "action")).post(form).build(), callTimeoutSec = 60))
    }

    private fun parseUpdate(body: String): AppUpdateInfo =
        runCatching { json.decodeFromString(AppUpdateInfo.serializer(), body) }.getOrElse { throw PiException("Antwort des Pi zum App-Update nicht lesbar") }

    /**
     * Downloads the offered APK to [dest] and checks size and SHA-256 against [info]; a file that does not match
     * is deleted. [onProgress] gets (bytes so far, expected bytes).
     */
    suspend fun downloadApp(info: AppUpdateInfo, dest: File, onProgress: (Long, Long) -> Unit = { _, _ -> }): File = withContext(Dispatchers.IO) {
        if (info.sha256.isBlank()) throw PiException("Der Pi nennt keine Prüfsumme – Update wird nicht geladen")
        val client = http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build()
        val tmp = File(dest.parentFile, dest.name + ".part")
        try {
            client.newCall(Request.Builder().url(url("api", "app", "android.apk")).build()).execute().use { r ->
                if (!r.isSuccessful) throw PiException(errorText(r.body?.string().orEmpty()) ?: "Pi antwortet mit HTTP ${r.code}")
                val body = r.body ?: throw PiException("Leere Antwort des Pi")
                val total = if (info.size > 0) info.size else body.contentLength()
                val md = MessageDigest.getInstance("SHA-256")
                var n = 0L
                body.byteStream().use { input -> tmp.outputStream().use { out ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val k = input.read(buf); if (k < 0) break
                        out.write(buf, 0, k); md.update(buf, 0, k); n += k
                        onProgress(n, total)
                    }
                } }
                if (info.size > 0 && n != info.size) throw PiException("Download unvollständig ($n von ${info.size} Bytes)")
                val hex = md.digest().joinToString("") { "%02x".format(it) }
                if (!hex.equals(info.sha256.trim(), ignoreCase = true)) throw PiException("Prüfsumme der Datei stimmt nicht – Download verworfen")
            }
            if (dest.exists()) dest.delete()
            if (!tmp.renameTo(dest)) throw PiException("Datei konnte nicht gespeichert werden")
            dest
        } catch (e: PiException) { tmp.delete(); throw e
        } catch (e: IOException) { tmp.delete(); throw PiException("Pi nicht erreichbar (${e.message ?: e.javaClass.simpleName})") }
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
        const val COORD_CONVENTION = "origin_top_right"

        val ACTIONS = setOf("home", "jog", "probe", "park", "light", "exhaust", "start", "autorun", "frame", "moveto", "motion_test", "motion_limits",
                            "abort", "estop", "estop_reset", "app_update_check")

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
