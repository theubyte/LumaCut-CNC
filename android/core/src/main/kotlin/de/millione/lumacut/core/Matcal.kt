package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Locale

/**
 * Adaptive material calibration on the Pi (feature "material_calibration",
 * op=matcal): engraving field by field with the camera, cutting pass by pass
 * until the camera sees the hole open. The Pi runs and stores it; the app
 * starts it and shows /api/status "material_calibration".
 */
@Serializable
data class MatcalSummary(
    val kind: String = "",
    val material: String = "",
    val state: String = "",
    val steps: Int = 0,
    /** Last field (engrave: target, power, speed, tone, clean) or pass (cut: square, speed, pass, ratio, fell). */
    val last: JsonObject? = null,
    /** engrave: {dunkel|mittel|hell: {power, speed, tone, approximate}}; cut: {squares, best}. */
    val result: JsonObject? = null,
    val saved: List<MatcalSaved> = emptyList(),
    val error: String = "",
)

@Serializable
data class MatcalSaved(val id: String = "", val name: String = "", val process: String = "")

object Matcal {
    const val FEATURE = "material_calibration"
    /** Test area from the laser point (machine mm, towards +X/+Y): engraving 6 × 3 fields with run-up, cutting 4 squares. */
    const val ENGRAVE_W = 51.0
    const val ENGRAVE_H = 21.0
    const val CUT_W = 44.0
    const val CUT_H = 8.0

    fun area(kind: String, x: Double, y: Double): Box =
        if (kind == "cut") Box(x, y, x + CUT_W, y + CUT_H) else Box(x - 3, y, x - 3 + ENGRAVE_W, y + ENGRAVE_H)

    private fun JsonObject.num(key: String) = this[key]?.jsonPrimitive?.doubleOrNull
    private fun fmt(v: Double, digits: Int = 0) = "%.${digits}f".format(Locale.GERMANY, v)

    /** One line about the step just measured. */
    fun lastStep(s: MatcalSummary): String? {
        val l = s.last ?: return null
        return if (s.kind == "engrave") {
            val clean = l["clean"]?.jsonPrimitive?.booleanOrNull == true
            "Feld ${s.steps}: ${fmt(l.num("power") ?: 0.0, 1)} % · ${fmt(l.num("speed") ?: 0.0)} mm/min → Ton ${fmt(l.num("tone") ?: 0.0, 2)}" +
                (if (clean) " · sauber" else " · streifig/Rand") + " (Ziel ${l["target"]?.jsonPrimitive?.content ?: "?"})"
        } else {
            val fell = l["fell"]?.jsonPrimitive?.booleanOrNull == true
            "${fmt(l.num("speed") ?: 0.0)} mm/min, Durchgang ${(l["pass"]?.jsonPrimitive?.intOrNull ?: 0) + 1}: " + if (fell) "durchgefallen" else "noch zu"
        }
    }

    /** Result lines: the tones found or the cutting setting with the least energy. */
    fun results(s: MatcalSummary): List<String> {
        val r = s.result ?: return emptyList()
        return if (s.kind == "engrave") listOf("dunkel", "mittel", "hell").mapNotNull { k ->
            val f = r[k]?.jsonObject ?: return@mapNotNull null
            val approx = f["approximate"]?.jsonPrimitive?.booleanOrNull == true
            "${k.replaceFirstChar { it.uppercase() }}: ${fmt(f.num("power") ?: 0.0, 1)} % · ${fmt(f.num("speed") ?: 0.0)} mm/min (Ton ${fmt(f.num("tone") ?: 0.0, 2)})" +
                if (approx) " – nur ungefähr" else ""
        } else {
            val squares = r["squares"]?.jsonArray?.map { it.jsonObject } ?: emptyList()
            val best = r["best"]?.takeIf { it is JsonObject }?.jsonObject
            squares.map { q ->
                val fell = q["fell"]?.jsonPrimitive?.booleanOrNull == true
                "${fmt(q.num("speed") ?: 0.0)} mm/min: " + if (fell) "${fmt(q.num("passes") ?: 0.0)} Durchgänge" else "nach ${fmt(q.num("passes") ?: 0.0)} nicht durch"
            } + listOfNotNull(best?.let { "Gespeichert: ${fmt(it.num("speed") ?: 0.0)} mm/min × ${fmt(it.num("passes") ?: 0.0)} (wenigste Energie)" })
        }
    }

    fun fields(kind: String, x: Double, y: Double, name: String, thicknessMm: Double, raised: Boolean): Map<String, String> = buildMap {
        put("kind", kind)
        put("x", "%.2f".format(Locale.ROOT, x))
        put("y", "%.2f".format(Locale.ROOT, y))
        put("name", name.trim())
        put("thickness", "%.2f".format(Locale.ROOT, thicknessMm))
        if (raised) put("raised", "1")
    }
}

/** Starts the calibration on the Pi; the Pi refuses with a German sentence when something is missing. */
suspend fun PiClient.materialCalibration(kind: String, machineX: Double, machineY: Double, name: String, thicknessMm: Double, raised: Boolean): String =
    action("matcal", Matcal.fields(kind, machineX, machineY, name, thicknessMm, raised))
