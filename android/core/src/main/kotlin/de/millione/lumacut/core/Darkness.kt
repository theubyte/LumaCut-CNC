package de.millione.lumacut.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.util.Locale
import kotlin.math.exp
import kotlin.math.ln

/** One field of the camera calibration (Pi `op=matcal`): tone 0 = untouched … 1 = black. */
@Serializable
data class DarknessPoint(val power: Double, val speed: Double, val tone: Double, val clean: Boolean = true)

/**
 * Darkness curve of a material as the Pi stores it with the engraving
 * materials (`tone_curve`, docs/MATERIAL_KALIBRIERUNG.md). The tone depends
 * on the energy per area, power / speed at [intervalMm]: the sliders move
 * along it with the same tone (slower and weaker) or along the tone.
 */
@Serializable
data class DarknessCurve(
    val points: List<DarknessPoint>,
    @SerialName("min_power_pct") val minPowerPct: Double = Darkness.RELIABLE_POWER_PCT,
    @SerialName("interval_mm") val intervalMm: Double = 0.1,
    @SerialName("speed_min") val speedMin: Double = 1500.0,
    @SerialName("speed_max") val speedMax: Double = 6000.0,
) {
    /** (ln energy, tone) by energy, the tone never falling: noise must not turn the curve back. */
    private val curve: List<Pair<Double, Double>>
        get() {
            var top = 0.0
            return points.filter { it.power > 0 && it.speed > 0 }.sortedBy { it.power / it.speed }
                .map { p -> top = maxOf(top, p.tone); ln(p.power / p.speed) to top }
        }

    val usable get() = curve.size >= 2 && curve.last().second > curve.first().second
    val toneRange get() = curve.first().second..curve.last().second

    /** Tone for energy per area [energy] (power % / mm/min at [intervalMm]); clamped to the measured range. */
    fun tone(energy: Double): Double {
        val x = ln(energy)
        if (x <= curve.first().first) return curve.first().second
        if (x >= curve.last().first) return curve.last().second
        val i = curve.indexOfLast { it.first <= x }.coerceAtMost(curve.size - 2)
        val (x0, t0) = curve[i]; val (x1, t1) = curve[i + 1]
        return if (x1 - x0 < 1e-9) t1 else t0 + (t1 - t0) * (x - x0) / (x1 - x0)
    }

    /** Energy per area for [tone], inverse of [tone]; clamped to the measured range. */
    fun energyFor(tone: Double): Double {
        val t = tone.coerceIn(toneRange)
        val i = curve.indexOfFirst { it.second >= t }.coerceAtLeast(1)
        val (x0, t0) = curve[i - 1]; val (x1, t1) = curve[i]
        return exp(if (t1 - t0 < 1e-9) x0 else x0 + (x1 - x0) * (t - t0) / (t1 - t0))
    }
}

/**
 * Speed and power moved together. "Präziser ↔ schneller" keeps power / speed
 * (same energy per mm, same tone) for every layer; "heller ↔ dunkler" needs a
 * fill layer with a [DarknessCurve]. Below [RELIABLE_POWER_PCT] the diode does
 * not fire reliably (dotted text on plywood 2026-10-29), so the power never
 * goes below it: a lighter tone then gets faster instead.
 */
object Darkness {
    const val RELIABLE_POWER_PCT = 8.0
    /** Slowest speed offered without a curve. */
    const val SPEED_FLOOR = 300.0

    data class Result(val layer: Layer, val limit: String? = null)

    private fun minPower(layer: Layer) = layer.darkness?.minPowerPct ?: RELIABLE_POWER_PCT

    /** Speeds reachable with the layer's energy per mm: power stays between the firing limit and 100 %. */
    fun speedRange(layer: Layer, maxFeed: Double): ClosedFloatingPointRange<Double> {
        val ratio = layer.powerPct / layer.speed
        val c = layer.darkness
        val lo = maxOf(minPower(layer) / ratio, c?.speedMin ?: SPEED_FLOOR)
        val hi = minOf(100.0 / ratio, c?.speedMax ?: maxFeed, maxFeed)
        return if (lo <= hi) lo..hi else hi..hi
    }

    /** Same energy per mm at [speed]; clamped to [speedRange] with the reason. */
    fun atSpeed(layer: Layer, speed: Double, maxFeed: Double): Result {
        val range = speedRange(layer, maxFeed)
        val v = speed.coerceIn(range)
        val limit = when {
            speed < range.start - 0.5 -> if (layer.powerPct * range.start / layer.speed <= minPower(layer) + 0.05)
                "Langsamer geht nicht: der Laser zündet unter %.0f %% nicht sicher.".format(minPower(layer))
                else "Langsamer ist nicht kalibriert."
            speed > range.endInclusive + 0.5 -> "Schneller geht nicht."
            else -> null
        }
        return Result(layer.copy(speed = v, powerPct = layer.powerPct * v / layer.speed), limit)
    }

    /** Slider position 0..1 (log scale) of the layer's speed within [speedRange]. */
    fun speedPosition(layer: Layer, maxFeed: Double): Double {
        val r = speedRange(layer, maxFeed)
        if (r.endInclusive - r.start < 1.0) return 0.5
        return (ln(layer.speed / r.start) / ln(r.endInclusive / r.start)).coerceIn(0.0, 1.0)
    }

    fun speedAt(layer: Layer, position: Double, maxFeed: Double): Double {
        val r = speedRange(layer, maxFeed)
        return r.start * exp(position.coerceIn(0.0, 1.0) * ln(r.endInclusive / r.start))
    }

    /** Tone the layer would give, or null without a curve or for lines (a single line is not a fill). */
    fun tone(layer: Layer): Double? {
        val c = layer.darkness?.takeIf { it.usable && layer.mode == LayerMode.FILL } ?: return null
        return c.tone(layer.powerPct / layer.speed * c.intervalMm / layer.intervalMm)
    }

    /**
     * [tone] at the layer's speed. A closer line interval than the curve's
     * overlaps more, so it needs less energy per mm. Power below the firing
     * limit → faster, above 100 % → slower.
     */
    fun atTone(layer: Layer, tone: Double, maxFeed: Double): Result {
        val c = layer.darkness?.takeIf { it.usable && layer.mode == LayerMode.FILL }
            ?: return Result(layer, "Für diese Ebene gibt es keine Schwärze-Kurve.")
        val ratio = c.energyFor(tone) * layer.intervalMm / c.intervalMm
        var v = layer.speed
        var limit: String? = null
        if (ratio * v < c.minPowerPct) v = c.minPowerPct / ratio
        if (ratio * v > 100.0) v = 100.0 / ratio
        if (v > maxFeed) { v = maxFeed; limit = "Heller geht nicht: der Laser zündet unter %.0f %% nicht sicher und ist schon am schnellsten.".format(c.minPowerPct) }
        val p = (ratio * v).coerceIn(c.minPowerPct, 100.0)
        if (limit == null && tone !in c.toneRange) limit = "Außerhalb der gemessenen Töne (%.2f–%.2f).".format(Locale.GERMANY, c.toneRange.start, c.toneRange.endInclusive)
        return Result(layer.copy(speed = v, powerPct = p), limit)
    }
}
