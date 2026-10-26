package de.millione.lumacut.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Material as the Pi stores it (docs/ZUSAMMENARBEIT_CLAUDE_GROK.md section 3,
 * /api/materials). Field names carry their unit; [id] is empty for new entries.
 */
@Serializable
data class PiMaterial(
    val id: String? = null,
    val name: String,
    @SerialName("thickness_mm") val thicknessMm: Double,
    val process: String = "Schneiden",
    val mode: String = "line",
    @SerialName("power_pct") val powerPct: Double,
    @SerialName("speed_mm_min") val speedMmMin: Double,
    val passes: Int = 1,
    @SerialName("interval_mm") val intervalMm: Double = 0.1,
    @SerialName("depth_per_pass_mm") val depthPerPassMm: Double = 0.0,
    @SerialName("z_step_mm") val zStepMm: Double = 0.0,
    val builtin: Boolean = false,
    val updated: String? = null,
) {
    fun toMaterial() = Material(
        id = id ?: name, name = name, thicknessMm = thicknessMm, process = process,
        mode = if (mode.equals("fill", true)) LayerMode.FILL else LayerMode.LINE,
        powerPct = powerPct, speed = speedMmMin, passes = passes, intervalMm = intervalMm,
        depthPerPassMm = depthPerPassMm, zStepMm = zStepMm, builtin = builtin,
    )
}

fun Material.toPi(newEntry: Boolean = false) = PiMaterial(
    id = if (newEntry) null else id, name = name, thicknessMm = thicknessMm, process = process,
    mode = if (mode == LayerMode.FILL) "fill" else "line", powerPct = powerPct, speedMmMin = speed,
    passes = passes, intervalMm = intervalMm, depthPerPassMm = depthPerPassMm, zStepMm = zStepMm, builtin = builtin,
)

/** GET /api/materials. */
@Serializable
data class MaterialList(val revision: Int = 0, val materials: List<PiMaterial> = emptyList())

/** One physical material (name and thickness) with its processes (Schneiden, Gravieren, Markieren). */
data class MaterialGroup(val name: String, val thicknessMm: Double, val entries: List<Material>) {
    val key get() = "$name|$thicknessMm"
    fun entry(process: String) = entries.firstOrNull { it.process.equals(process, true) }
    val processes get() = entries.map { it.process }.distinct()
}

fun List<Material>.grouped(query: String = ""): List<MaterialGroup> {
    val q = query.trim().lowercase()
    return filter { q.isEmpty() || it.name.lowercase().contains(q) || it.process.lowercase().contains(q) }
        .groupBy { it.name to it.thicknessMm }
        .map { (k, v) -> MaterialGroup(k.first, k.second, v) }
        .sortedWith(compareBy({ it.name.lowercase() }, { it.thicknessMm }))
}

/** The Pi refused a change because [revision] is stale (HTTP 409): reload the list and try again. */
class PiConflictException(message: String, val revision: Int?) : PiException(message)
