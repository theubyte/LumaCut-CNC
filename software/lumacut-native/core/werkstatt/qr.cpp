#include "core/werkstatt/qr.h"
#include <QByteArray>
#include <algorithm>
#include <climits>
#include <cstdlib>
#include <stdexcept>

namespace lumacut::Qr {

namespace {
constexpr int ECC_PER_BLOCK_M[] = {-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26};
constexpr int BLOCKS_M[] = {-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5};

int rawModules(int ver) {
    int result = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
        const int align = ver / 7 + 2;
        result -= (25 * align - 10) * align - 55;
        if (ver >= 7) result -= 36;
    }
    return result;
}
int dataCodewords(int ver) { return rawModules(ver) / 8 - ECC_PER_BLOCK_M[ver] * BLOCKS_M[ver]; }

int rsMul(int x, int y) {
    int z = 0;
    for (int i = 7; i >= 0; --i) {
        z = (z << 1) ^ ((z >> 7) * 0x11D);
        z ^= ((y >> i) & 1) * x;
    }
    return z;
}

std::vector<int> interleave(int ver, const std::vector<int>& data) {
    const int blocks = BLOCKS_M[ver], eccLen = ECC_PER_BLOCK_M[ver], raw = rawModules(ver) / 8;
    const int shortBlocks = blocks - raw % blocks, shortLen = raw / blocks;
    const std::vector<int> divisor = rsDivisor(eccLen);
    std::vector<std::vector<int>> all;
    size_t k = 0;
    for (int i = 0; i < blocks; ++i) {
        const size_t len = size_t(shortLen - eccLen + (i < shortBlocks ? 0 : 1));
        std::vector<int> block(data.begin() + std::ptrdiff_t(k), data.begin() + std::ptrdiff_t(k + len));
        k += len;
        const std::vector<int> ecc = rsRemainder(block, divisor);
        if (i < shortBlocks) block.push_back(0);
        block.insert(block.end(), ecc.begin(), ecc.end());
        all.push_back(std::move(block));
    }
    std::vector<int> out;
    for (size_t i = 0; i < all[0].size(); ++i)
        for (int j = 0; j < blocks; ++j)
            if (int(i) != shortLen - eccLen || j >= shortBlocks) out.push_back(all[size_t(j)][i]);
    return out;
}

class Builder {
public:
    explicit Builder(int ver) : ver(ver), size(ver * 4 + 17), mod(size_t(size * size), 0), fn(size_t(size * size), 0) {}
    int ver, size;
    std::vector<uint8_t> mod, fn;

    uint8_t& at(int x, int y) { return mod[size_t(y) * size_t(size) + size_t(x)]; }
    bool isFn(int x, int y) const { return fn[size_t(y) * size_t(size) + size_t(x)] != 0; }
    void setFn(int x, int y, bool dark) { at(x, y) = dark; fn[size_t(y) * size_t(size) + size_t(x)] = 1; }

    void drawFunctionPatterns() {
        for (int i = 0; i < size; ++i) { setFn(6, i, i % 2 == 0); setFn(i, 6, i % 2 == 0); }
        finder(3, 3);
        finder(size - 4, 3);
        finder(3, size - 4);
        const std::vector<int> pos = alignPositions();
        const int n = int(pos.size());
        for (int i = 0; i < n; ++i)
            for (int j = 0; j < n; ++j) {
                if ((i == 0 && j == 0) || (i == 0 && j == n - 1) || (i == n - 1 && j == 0)) continue;
                for (int dy = -2; dy <= 2; ++dy)
                    for (int dx = -2; dx <= 2; ++dx) setFn(pos[size_t(i)] + dx, pos[size_t(j)] + dy, std::max(std::abs(dx), std::abs(dy)) != 1);
            }
        drawFormat(0);
        drawVersion();
    }
    void finder(int x, int y) {
        for (int dy = -4; dy <= 4; ++dy)
            for (int dx = -4; dx <= 4; ++dx) {
                const int d = std::max(std::abs(dx), std::abs(dy)), xx = x + dx, yy = y + dy;
                if (xx >= 0 && xx < size && yy >= 0 && yy < size) setFn(xx, yy, d != 2 && d != 4);
            }
    }
    std::vector<int> alignPositions() const {
        if (ver == 1) return {};
        const int n = ver / 7 + 2;
        const int step = (ver * 4 + n * 2 + 1) / (n * 2 - 2) * 2;
        std::vector<int> r(size_t(n), 0);
        r[0] = 6;
        for (int i = 0; i < n - 1; ++i) r[size_t(n - 1 - i)] = size - 7 - i * step;
        return r;
    }
    /** Format bits for level M (00) and the mask. */
    void drawFormat(int mask) {
        int rem = mask;
        for (int k = 0; k < 10; ++k) rem = (rem << 1) ^ ((rem >> 9) * 0x537);
        const int bits = ((mask << 10) | rem) ^ 0x5412;
        const auto bit = [&](int i) { return ((bits >> i) & 1) != 0; };
        for (int i = 0; i <= 5; ++i) setFn(8, i, bit(i));
        setFn(8, 7, bit(6));
        setFn(8, 8, bit(7));
        setFn(7, 8, bit(8));
        for (int i = 9; i <= 14; ++i) setFn(14 - i, 8, bit(i));
        for (int i = 0; i <= 7; ++i) setFn(size - 1 - i, 8, bit(i));
        for (int i = 8; i <= 14; ++i) setFn(8, size - 15 + i, bit(i));
        setFn(8, size - 8, true);
    }
    void drawVersion() {
        if (ver < 7) return;
        int rem = ver;
        for (int k = 0; k < 12; ++k) rem = (rem << 1) ^ ((rem >> 11) * 0x1F25);
        const int bits = (ver << 12) | rem;
        for (int i = 0; i <= 17; ++i) {
            const bool c = ((bits >> i) & 1) != 0;
            const int a = size - 11 + i % 3, b = i / 3;
            setFn(a, b, c);
            setFn(b, a, c);
        }
    }
    void drawCodewords(const std::vector<int>& data) {
        size_t i = 0;
        for (int right = size - 1; right >= 1; right -= 2) {
            if (right == 6) right = 5;
            for (int vert = 0; vert < size; ++vert)
                for (int j = 0; j <= 1; ++j) {
                    const int x = right - j;
                    const bool upward = ((right + 1) & 2) == 0;
                    const int y = upward ? size - 1 - vert : vert;
                    if (!isFn(x, y) && i < data.size() * 8) {
                        at(x, y) = ((data[i >> 3] >> (7 - (i & 7))) & 1) != 0;
                        ++i;
                    }
                }
        }
    }
    void applyMask(int m) {
        for (int y = 0; y < size; ++y)
            for (int x = 0; x < size; ++x)
                if (maskBit(m, x, y) && !isFn(x, y)) at(x, y) ^= 1;
    }
    int penalty() {
        static constexpr bool P1[] = {true, false, true, true, true, false, true, false, false, false, false};
        static constexpr bool P2[] = {false, false, false, false, true, false, true, true, true, false, true};
        int result = 0;
        const auto line = [&](auto get) {
            int run = 1;
            for (int i = 1; i < size; ++i) {
                if (get(i) == get(i - 1)) {
                    ++run;
                    if (run == 5) result += 3;
                    else if (run > 5) ++result;
                } else run = 1;
            }
            for (int a = 0; a <= size - 11; ++a) {
                bool m1 = true, m2 = true;
                for (int k = 0; k < 11; ++k) {
                    if (get(a + k) != P1[k]) m1 = false;
                    if (get(a + k) != P2[k]) m2 = false;
                }
                if (m1 || m2) result += 40;
            }
        };
        for (int y = 0; y < size; ++y) line([&](int i) { return at(i, y) != 0; });
        for (int x = 0; x < size; ++x) line([&](int i) { return at(x, i) != 0; });
        for (int y = 0; y < size - 1; ++y)
            for (int x = 0; x < size - 1; ++x) {
                const uint8_t c = at(x, y);
                if (c == at(x + 1, y) && c == at(x, y + 1) && c == at(x + 1, y + 1)) result += 3;
            }
        int dark = 0;
        for (const uint8_t v : mod) dark += v;
        const int total = size * size;
        const int k = (std::abs(dark * 20 - total * 10) + total - 1) / total - 1;
        return result + k * 10;
    }
};
}  // namespace

int capacity(int version) { return (dataCodewords(version) * 8 - 4 - (version < 10 ? 8 : 16)) / 8; }

std::vector<int> rsDivisor(int degree) {
    std::vector<int> result(size_t(degree), 0);
    result[size_t(degree - 1)] = 1;
    int root = 1;
    for (int k = 0; k < degree; ++k) {
        for (int j = 0; j < degree; ++j) {
            result[size_t(j)] = rsMul(result[size_t(j)], root);
            if (j + 1 < degree) result[size_t(j)] ^= result[size_t(j + 1)];
        }
        root = rsMul(root, 2);
    }
    return result;
}

std::vector<int> rsRemainder(const std::vector<int>& data, const std::vector<int>& divisor) {
    std::vector<int> result(divisor.size(), 0);
    for (const int b : data) {
        const int factor = b ^ result[0];
        result.erase(result.begin());
        result.push_back(0);
        for (size_t i = 0; i < result.size(); ++i) result[i] ^= rsMul(divisor[i], factor);
    }
    return result;
}

bool maskBit(int m, int x, int y) {
    switch (m) {
    case 0: return (x + y) % 2 == 0;
    case 1: return y % 2 == 0;
    case 2: return x % 3 == 0;
    case 3: return (x + y) % 3 == 0;
    case 4: return (x / 3 + y / 2) % 2 == 0;
    case 5: return x * y % 2 + x * y % 3 == 0;
    case 6: return (x * y % 2 + x * y % 3) % 2 == 0;
    default: return ((x + y) % 2 + x * y % 3) % 2 == 0;
    }
}

Code encode(const QString& text) {
    const QByteArray bytes = text.toUtf8();
    if (bytes.isEmpty()) throw std::invalid_argument("Kein Text für den QR-Code.");
    int version = 0;
    for (int v = 1; v <= MAX_VERSION; ++v)
        if (bytes.size() <= capacity(v)) { version = v; break; }
    if (!version)
        throw std::invalid_argument(QStringLiteral("Der Text ist zu lang für den QR-Code (höchstens %1 Zeichen).").arg(capacity(MAX_VERSION)).toStdString());
    const size_t cap = size_t(dataCodewords(version)) * 8;
    std::vector<uint8_t> bits;
    const auto put = [&](int value, int n) { for (int i = n - 1; i >= 0; --i) bits.push_back(uint8_t((value >> i) & 1)); };
    put(4, 4);
    put(int(bytes.size()), version < 10 ? 8 : 16);
    for (const char c : bytes) put(uint8_t(c), 8);
    put(0, int(std::min<size_t>(4, cap - bits.size())));
    while (bits.size() % 8) bits.push_back(0);
    int pad = 0xEC;
    while (bits.size() < cap) { put(pad, 8); pad ^= 0xEC ^ 0x11; }
    std::vector<int> data;
    for (size_t i = 0; i < bits.size(); i += 8) {
        int v = 0;
        for (size_t k = 0; k < 8; ++k) v = (v << 1) | bits[i + k];
        data.push_back(v);
    }
    Builder b(version);
    b.drawFunctionPatterns();
    b.drawCodewords(interleave(version, data));
    int best = 0, bestPenalty = INT_MAX;
    for (int m = 0; m < 8; ++m) {
        b.applyMask(m);
        b.drawFormat(m);
        const int p = b.penalty();
        if (p < bestPenalty) { bestPenalty = p; best = m; }
        b.applyMask(m);
    }
    b.applyMask(best);
    b.drawFormat(best);
    return {version, b.size, best, std::move(b.mod)};
}

PolySet polys(const Code& q, double m) {
    PolySet out;
    for (int y = 0; y < q.size; ++y) {
        int x = 0;
        while (x < q.size) {
            if (!q.dark(x, y)) { ++x; continue; }
            int e = x;
            while (e < q.size && q.dark(e, y)) ++e;
            out.add({Pt{x * m, y * m}, Pt{e * m, y * m}, Pt{e * m, (y + 1) * m}, Pt{x * m, (y + 1) * m}, Pt{x * m, y * m}});
            x = e;
        }
    }
    return out;
}

}  // namespace lumacut::Qr
