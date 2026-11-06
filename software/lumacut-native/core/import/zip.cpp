#include "core/import/zip.h"
#include "core/import/vector.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

namespace lumacut::import {
namespace {

constexpr qsizetype MAX_ENTRY = 40 * 1024 * 1024;
constexpr qsizetype MAX_TOTAL = 4 * MAX_ENTRY;

QString notZip() { return QStringLiteral("Das ZIP-Archiv ist beschädigt."); }
QString tooBig() { return QStringLiteral("Die Datei ist zu groß."); }

inline uint32_t u16(const char* p) { return uint32_t(uint8_t(p[0])) | uint32_t(uint8_t(p[1])) << 8; }
inline uint32_t u32(const char* p) { return u16(p) | u16(p + 2) << 16; }

struct Entry {
    QString name;
    uint32_t method, compressed, size, offset;
};

std::vector<Entry> directory(const QByteArray& b) {
    const qsizetype n = b.size();
    if (n < 22) throw ImportError(notZip());
    const char* d = b.constData();
    qsizetype eocd = -1;
    for (qsizetype i = n - 22; i >= 0 && i >= n - 22 - 65535; --i)
        if (u32(d + i) == 0x06054B50) { eocd = i; break; }
    if (eocd < 0) throw ImportError(notZip());
    const uint32_t count = u16(d + eocd + 10);
    qint64 p = u32(d + eocd + 16);
    std::vector<Entry> out;
    out.reserve(count);
    for (uint32_t k = 0; k < count; ++k) {
        if (p + 46 > n || u32(d + p) != 0x02014B50) throw ImportError(notZip());
        const uint32_t nameLen = u16(d + p + 28), extra = u16(d + p + 30), comment = u16(d + p + 32);
        if (p + 46 + nameLen > n) throw ImportError(notZip());
        out.push_back({QString::fromUtf8(d + p + 46, nameLen), u16(d + p + 10), u32(d + p + 20), u32(d + p + 24), u32(d + p + 42)});
        p += 46 + qint64(nameLen) + extra + comment;
    }
    return out;
}

/** Inflate nach dem Muster von zlibs puff: kanonische Huffman-Codes, jedes Bit geprüft. Klein, sicher, schnell genug für Projektdateien. */
class Inflater {
public:
    Inflater(const char* data, qsizetype size, qsizetype limit) : m_in(reinterpret_cast<const uint8_t*>(data)), m_size(size), m_limit(limit) {}

    QByteArray run() {
        m_out.reserve(std::min<qsizetype>(m_size * 3 + 64, m_limit));
        for (bool last = false; !last;) {
            last = bits(1) != 0;
            const uint32_t type = bits(2);
            if (type == 0) stored();
            else if (type == 1) fixedBlock();
            else if (type == 2) dynamicBlock();
            else throw ImportError(notZip());
        }
        return m_out;
    }

private:
    struct Huffman {
        uint16_t count[16] = {};
        uint16_t symbol[320] = {};
    };

    uint32_t bits(int need) {
        uint32_t val = m_bitBuf;
        while (m_bitCnt < need) {
            if (m_pos >= m_size) throw ImportError(notZip());
            val |= uint32_t(m_in[m_pos++]) << m_bitCnt;
            m_bitCnt += 8;
        }
        m_bitBuf = val >> need;
        m_bitCnt -= need;
        return val & ((1u << need) - 1);
    }
    int decode(const Huffman& h) {
        int code = 0, first = 0, index = 0;
        for (int len = 1; len <= 15; ++len) {
            code |= int(bits(1));
            const int count = h.count[len];
            if (code - count < first) return h.symbol[index + (code - first)];
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        throw ImportError(notZip());
    }
    static int construct(Huffman& h, const uint8_t* length, int n) {
        std::memset(h.count, 0, sizeof h.count);
        for (int s = 0; s < n; ++s) ++h.count[length[s]];
        if (h.count[0] == n) return 0;
        int left = 1;
        for (int len = 1; len <= 15; ++len) {
            left <<= 1;
            left -= h.count[len];
            if (left < 0) return left;
        }
        uint16_t offs[16];
        offs[1] = 0;
        for (int len = 1; len < 15; ++len) offs[len + 1] = uint16_t(offs[len] + h.count[len]);
        for (int s = 0; s < n; ++s) if (length[s] != 0) h.symbol[offs[length[s]]++] = uint16_t(s);
        return left;
    }
    void stored() {
        m_bitBuf = 0;
        m_bitCnt = 0;
        if (m_pos + 4 > m_size) throw ImportError(notZip());
        const uint32_t len = uint32_t(m_in[m_pos]) | uint32_t(m_in[m_pos + 1]) << 8;
        const uint32_t nlen = uint32_t(m_in[m_pos + 2]) | uint32_t(m_in[m_pos + 3]) << 8;
        if (len != (~nlen & 0xFFFF)) throw ImportError(notZip());
        m_pos += 4;
        if (m_pos + len > m_size) throw ImportError(notZip());
        if (m_out.size() + len > m_limit) throw ImportError(tooBig());
        m_out.append(reinterpret_cast<const char*>(m_in + m_pos), len);
        m_pos += len;
    }
    void codes(const Huffman& lit, const Huffman& dist) {
        static const uint16_t lens[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
        static const uint8_t lext[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
        static const uint16_t dists[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
        static const uint8_t dext[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};
        for (;;) {
            int sym = decode(lit);
            if (sym < 256) {
                if (m_out.size() >= m_limit) throw ImportError(tooBig());
                m_out.append(char(sym));
            } else if (sym == 256) {
                return;
            } else {
                sym -= 257;
                if (sym >= 29) throw ImportError(notZip());
                const int len = lens[sym] + int(bits(lext[sym]));
                const int ds = decode(dist);
                if (ds >= 30) throw ImportError(notZip());
                const qsizetype d = dists[ds] + qsizetype(bits(dext[ds]));
                if (d > m_out.size()) throw ImportError(notZip());
                if (m_out.size() + len > m_limit) throw ImportError(tooBig());
                const qsizetype at = m_out.size();
                m_out.resize(at + len);
                char* o = m_out.data();
                for (qsizetype i = 0; i < len; ++i) o[at + i] = o[at - d + i];
            }
        }
    }
    void fixedBlock() {
        static const auto tables = [] {
            struct { Huffman lit, dist; } t;
            uint8_t l[320];
            int s = 0;
            for (; s < 144; ++s) l[s] = 8;
            for (; s < 256; ++s) l[s] = 9;
            for (; s < 280; ++s) l[s] = 7;
            for (; s < 288; ++s) l[s] = 8;
            construct(t.lit, l, 288);
            for (s = 0; s < 30; ++s) l[s] = 5;
            construct(t.dist, l, 30);
            return t;
        }();
        codes(tables.lit, tables.dist);
    }
    void dynamicBlock() {
        static const uint8_t order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
        const int nlen = int(bits(5)) + 257, ndist = int(bits(5)) + 1, ncode = int(bits(4)) + 4;
        if (nlen > 286 || ndist > 30) throw ImportError(notZip());
        uint8_t lengths[320] = {};
        int index = 0;
        for (; index < ncode; ++index) lengths[order[index]] = uint8_t(bits(3));
        for (; index < 19; ++index) lengths[order[index]] = 0;
        Huffman lencode, distcode;
        if (construct(lencode, lengths, 19) != 0) throw ImportError(notZip());
        std::memset(lengths, 0, sizeof lengths);
        index = 0;
        while (index < nlen + ndist) {
            int sym = decode(lencode);
            if (sym < 16) { lengths[index++] = uint8_t(sym); continue; }
            int len = 0, rep = 0;
            if (sym == 16) {
                if (index == 0) throw ImportError(notZip());
                len = lengths[index - 1];
                rep = 3 + int(bits(2));
            } else if (sym == 17) rep = 3 + int(bits(3));
            else rep = 11 + int(bits(7));
            if (index + rep > nlen + ndist) throw ImportError(notZip());
            while (rep--) lengths[index++] = uint8_t(len);
        }
        if (lengths[256] == 0) throw ImportError(notZip());
        int err = construct(lencode, lengths, nlen);
        if (err != 0 && (err < 0 || nlen != lencode.count[0] + lencode.count[1])) throw ImportError(notZip());
        err = construct(distcode, lengths + nlen, ndist);
        if (err != 0 && (err < 0 || ndist != distcode.count[0] + distcode.count[1])) throw ImportError(notZip());
        codes(lencode, distcode);
    }

    const uint8_t* m_in;
    qsizetype m_size, m_limit, m_pos = 0;
    uint32_t m_bitBuf = 0;
    int m_bitCnt = 0;
    QByteArray m_out;
};

}  // namespace

QByteArray inflateRaw(const char* data, qsizetype size, qsizetype limit) { return Inflater(data, size, limit).run(); }

QStringList zipNames(const QByteArray& b) {
    QStringList out;
    for (const Entry& e : directory(b)) out.push_back(e.name);
    return out;
}

QHash<QString, QByteArray> readZip(const QByteArray& b) {
    QHash<QString, QByteArray> out;
    const char* d = b.constData();
    const qint64 n = b.size();
    qint64 total = 0;
    for (const Entry& e : directory(b)) {
        if (e.name.endsWith(QLatin1Char('/'))) continue;
        const qint64 off = e.offset;
        if (off + 30 > n || u32(d + off) != 0x04034B50) throw ImportError(notZip());
        const qint64 start = off + 30 + u16(d + off + 26) + u16(d + off + 28);
        if (start + qint64(e.compressed) > n) throw ImportError(notZip());
        QByteArray data;
        if (e.method == 0) {
            if (e.compressed > quint64(MAX_ENTRY)) throw ImportError(tooBig());
            data = QByteArray(d + start, qsizetype(e.compressed));
        } else if (e.method == 8) {
            data = inflateRaw(d + start, qsizetype(e.compressed), MAX_ENTRY);
        } else {
            throw ImportError(QStringLiteral("Das ZIP-Archiv nutzt eine unbekannte Kompression."));
        }
        total += data.size();
        if (total > MAX_TOTAL) throw ImportError(tooBig());
        out.insert(e.name, std::move(data));
    }
    return out;
}

}  // namespace lumacut::import
