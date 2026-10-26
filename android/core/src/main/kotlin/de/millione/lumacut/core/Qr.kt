package de.millione.lumacut.core

import kotlin.math.abs

/**
 * QR code (ISO 18004) in byte mode with error correction level M, versions 1 to 10
 * (up to 213 bytes of text). The mask with the lowest penalty is chosen.
 */
class QrCode private constructor(val version: Int, val size: Int, val mask: Int, private val dark: Array<BooleanArray>) {
    /** True = dark module at column [x], row [y]. */
    operator fun get(x: Int, y: Int) = x in 0 until size && y in 0 until size && dark[y][x]

    /**
     * Filled rectangles (one per horizontal run of dark modules) for engraving with a module edge of [moduleMm];
     * the top-left corner is at (0, 0). Quiet zone is not included: leave a light margin around the code.
     */
    fun toPolys(moduleMm: Double): List<Poly> {
        val out = ArrayList<Poly>()
        for (y in 0 until size) {
            var x = 0
            while (x < size) {
                if (!this[x, y]) { x++; continue }
                var e = x
                while (e < size && this[e, y]) e++
                out += listOf(Pt(x * moduleMm, y * moduleMm), Pt(e * moduleMm, y * moduleMm), Pt(e * moduleMm, (y + 1) * moduleMm),
                              Pt(x * moduleMm, (y + 1) * moduleMm), Pt(x * moduleMm, y * moduleMm))
                x = e
            }
        }
        return out
    }

    companion object {
        /** Smallest module edge that still scans reliably when engraved. */
        const val MIN_MODULE_MM = 0.8

        private val ECC_PER_BLOCK_M = intArrayOf(-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
        private val BLOCKS_M = intArrayOf(-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
        const val MAX_VERSION = 10

        /** Bytes of text that fit into [version] at level M. */
        fun capacity(version: Int): Int {
            val data = dataCodewords(version)
            val countBits = if (version < 10) 8 else 16
            return (data * 8 - 4 - countBits) / 8
        }

        private fun rawModules(ver: Int): Int {
            var result = (16 * ver + 128) * ver + 64
            if (ver >= 2) {
                val align = ver / 7 + 2
                result -= (25 * align - 10) * align - 55
                if (ver >= 7) result -= 36
            }
            return result
        }

        private fun dataCodewords(ver: Int) = rawModules(ver) / 8 - ECC_PER_BLOCK_M[ver] * BLOCKS_M[ver]

        fun encode(text: String): QrCode {
            val bytes = text.toByteArray(Charsets.UTF_8)
            require(bytes.isNotEmpty()) { "Kein Text für den QR-Code" }
            val version = (1..MAX_VERSION).firstOrNull { bytes.size <= capacity(it) }
                ?: throw IllegalArgumentException("Text zu lang für den QR-Code (höchstens ${capacity(MAX_VERSION)} Zeichen)")
            val cap = dataCodewords(version) * 8
            val bits = ArrayList<Boolean>()
            fun put(value: Int, n: Int) { for (i in n - 1 downTo 0) bits += ((value ushr i) and 1) != 0 }
            put(4, 4); put(bytes.size, if (version < 10) 8 else 16)
            for (b in bytes) put(b.toInt() and 0xFF, 8)
            put(0, minOf(4, cap - bits.size))
            while (bits.size % 8 != 0) bits += false
            var pad = 0xEC
            while (bits.size < cap) { put(pad, 8); pad = pad xor 0xEC xor 0x11 }
            val data = ByteArray(bits.size / 8) { i -> var v = 0; for (k in 0 until 8) v = (v shl 1) or (if (bits[i * 8 + k]) 1 else 0); v.toByte() }
            val words = interleave(version, data)

            val builder = Builder(version)
            builder.drawFunctionPatterns()
            builder.drawCodewords(words)
            var best = 0; var bestPenalty = Int.MAX_VALUE
            for (m in 0 until 8) {
                builder.applyMask(m); builder.drawFormat(m)
                val p = builder.penalty()
                if (p < bestPenalty) { bestPenalty = p; best = m }
                builder.applyMask(m)   // undo (xor)
            }
            builder.applyMask(best); builder.drawFormat(best)
            return QrCode(version, builder.size, best, builder.modules)
        }

        private fun interleave(ver: Int, data: ByteArray): ByteArray {
            val blocks = BLOCKS_M[ver]; val eccLen = ECC_PER_BLOCK_M[ver]
            val raw = rawModules(ver) / 8
            val short = blocks - raw % blocks; val shortLen = raw / blocks
            val divisor = rsDivisor(eccLen)
            val all = ArrayList<IntArray>()
            var k = 0
            for (i in 0 until blocks) {
                val len = shortLen - eccLen + (if (i < short) 0 else 1)
                val dat = data.copyOfRange(k, k + len).map { it.toInt() and 0xFF }.toIntArray(); k += len
                val ecc = rsRemainder(dat, divisor)
                val padded = if (i < short) dat + intArrayOf(0) else dat
                all += padded + ecc
            }
            val out = ArrayList<Byte>()
            for (i in 0 until all[0].size) for (j in 0 until blocks) {
                if (i != shortLen - eccLen || j >= short) out += all[j][i].toByte()
            }
            return out.toByteArray()
        }

        internal fun rsDivisor(degree: Int): IntArray {
            val result = IntArray(degree); result[degree - 1] = 1
            var root = 1
            repeat(degree) {
                for (j in result.indices) {
                    result[j] = rsMul(result[j], root)
                    if (j + 1 < result.size) result[j] = result[j] xor result[j + 1]
                }
                root = rsMul(root, 0x02)
            }
            return result
        }

        internal fun rsRemainder(data: IntArray, divisor: IntArray): IntArray {
            val result = IntArray(divisor.size)
            for (b in data) {
                val factor = b xor result[0]
                for (i in 0 until result.size - 1) result[i] = result[i + 1]
                result[result.size - 1] = 0
                for (i in result.indices) result[i] = result[i] xor rsMul(divisor[i], factor)
            }
            return result
        }

        private fun rsMul(x: Int, y: Int): Int {
            var z = 0
            for (i in 7 downTo 0) {
                z = (z shl 1) xor ((z ushr 7) * 0x11D)
                z = z xor (((y ushr i) and 1) * x)
            }
            return z
        }

        internal class Builder(val ver: Int) {
            val size = ver * 4 + 17
            val modules = Array(size) { BooleanArray(size) }
            val isFunction = Array(size) { BooleanArray(size) }

            private fun setFn(x: Int, y: Int, dark: Boolean) { modules[y][x] = dark; isFunction[y][x] = true }
            private fun bit(v: Int, i: Int) = ((v ushr i) and 1) != 0

            fun drawFunctionPatterns() {
                for (i in 0 until size) { setFn(6, i, i % 2 == 0); setFn(i, 6, i % 2 == 0) }
                finder(3, 3); finder(size - 4, 3); finder(3, size - 4)
                val pos = alignPositions()
                for (i in pos.indices) for (j in pos.indices) {
                    if ((i == 0 && j == 0) || (i == 0 && j == pos.size - 1) || (i == pos.size - 1 && j == 0)) continue
                    alignment(pos[i], pos[j])
                }
                drawFormat(0)
                drawVersion()
            }

            private fun finder(x: Int, y: Int) {
                for (dy in -4..4) for (dx in -4..4) {
                    val d = maxOf(abs(dx), abs(dy)); val xx = x + dx; val yy = y + dy
                    if (xx in 0 until size && yy in 0 until size) setFn(xx, yy, d != 2 && d != 4)
                }
            }

            private fun alignment(x: Int, y: Int) {
                for (dy in -2..2) for (dx in -2..2) setFn(x + dx, y + dy, maxOf(abs(dx), abs(dy)) != 1)
            }

            fun alignPositions(): IntArray {
                if (ver == 1) return IntArray(0)
                val n = ver / 7 + 2
                val step = if (ver == 32) 26 else (ver * 4 + n * 2 + 1) / (n * 2 - 2) * 2
                val r = IntArray(n); r[0] = 6
                for (i in 0 until n - 1) r[n - 1 - i] = size - 7 - i * step
                return r
            }

            /** Format bits for level M (00) and [mask]. */
            fun drawFormat(mask: Int) {
                val data = (0 shl 3) or mask
                var rem = data
                repeat(10) { rem = (rem shl 1) xor ((rem ushr 9) * 0x537) }
                val bits = ((data shl 10) or rem) xor 0x5412
                for (i in 0..5) setFn(8, i, bit(bits, i))
                setFn(8, 7, bit(bits, 6)); setFn(8, 8, bit(bits, 7)); setFn(7, 8, bit(bits, 8))
                for (i in 9..14) setFn(14 - i, 8, bit(bits, i))
                for (i in 0..7) setFn(size - 1 - i, 8, bit(bits, i))
                for (i in 8..14) setFn(8, size - 15 + i, bit(bits, i))
                setFn(8, size - 8, true)
            }

            private fun drawVersion() {
                if (ver < 7) return
                var rem = ver
                repeat(12) { rem = (rem shl 1) xor ((rem ushr 11) * 0x1F25) }
                val bits = (ver shl 12) or rem
                for (i in 0..17) {
                    val c = bit(bits, i); val a = size - 11 + i % 3; val b = i / 3
                    setFn(a, b, c); setFn(b, a, c)
                }
            }

            fun drawCodewords(data: ByteArray) {
                var i = 0
                var right = size - 1
                while (right >= 1) {
                    if (right == 6) right = 5
                    for (vert in 0 until size) for (j in 0..1) {
                        val x = right - j
                        val upward = ((right + 1) and 2) == 0
                        val y = if (upward) size - 1 - vert else vert
                        if (!isFunction[y][x] && i < data.size * 8) {
                            modules[y][x] = bit(data[i ushr 3].toInt() and 0xFF, 7 - (i and 7)); i++
                        }
                    }
                    right -= 2
                }
            }

            fun applyMask(m: Int) {
                for (y in 0 until size) for (x in 0 until size) {
                    val invert = when (m) {
                        0 -> (x + y) % 2 == 0
                        1 -> y % 2 == 0
                        2 -> x % 3 == 0
                        3 -> (x + y) % 3 == 0
                        4 -> (x / 3 + y / 2) % 2 == 0
                        5 -> x * y % 2 + x * y % 3 == 0
                        6 -> (x * y % 2 + x * y % 3) % 2 == 0
                        else -> ((x + y) % 2 + x * y % 3) % 2 == 0
                    }
                    if (invert && !isFunction[y][x]) modules[y][x] = !modules[y][x]
                }
            }

            fun penalty(): Int {
                var result = 0
                val pattern1 = booleanArrayOf(true, false, true, true, true, false, true, false, false, false, false)
                val pattern2 = booleanArrayOf(false, false, false, false, true, false, true, true, true, false, true)
                fun line(get: (Int) -> Boolean) {
                    var run = 1
                    for (i in 1 until size) {
                        if (get(i) == get(i - 1)) { run++; if (run == 5) result += 3 else if (run > 5) result++ } else run = 1
                    }
                    for (s in 0..size - 11) {
                        if ((0 until 11).all { get(s + it) == pattern1[it] } || (0 until 11).all { get(s + it) == pattern2[it] }) result += 40
                    }
                }
                for (y in 0 until size) line { modules[y][it] }
                for (x in 0 until size) line { modules[it][x] }
                for (y in 0 until size - 1) for (x in 0 until size - 1) {
                    val c = modules[y][x]
                    if (c == modules[y][x + 1] && c == modules[y + 1][x] && c == modules[y + 1][x + 1]) result += 3
                }
                val total = size * size
                val darkCount = modules.sumOf { row -> row.count { it } }
                val k = (abs(darkCount * 20 - total * 10) + total - 1) / total - 1
                return result + k * 10
            }
        }
    }
}
