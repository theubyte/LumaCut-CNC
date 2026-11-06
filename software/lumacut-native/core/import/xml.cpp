#include "core/import/xml.h"

#include <cstring>

namespace lumacut::import {
namespace {

inline bool isSpace(char c) { return c == ' ' || c == '\n' || c == '\t' || c == '\r'; }
inline bool isNameEnd(char c) { return isSpace(c) || c == '/' || c == '>' || c == '='; }

inline bool startsAt(QByteArrayView s, qsizetype i, const char* lit, qsizetype n) {
    return i + n <= s.size() && std::memcmp(s.data() + i, lit, size_t(n)) == 0;
}
inline qsizetype findChar(QByteArrayView s, qsizetype from, char c) {
    if (from >= s.size()) return -1;
    const void* p = std::memchr(s.data() + from, c, size_t(s.size() - from));
    return p ? static_cast<const char*>(p) - s.data() : -1;
}
qsizetype findLit(QByteArrayView s, qsizetype from, const char* lit, qsizetype n) {
    for (qsizetype i = findChar(s, from, lit[0]); i >= 0; i = findChar(s, i + 1, lit[0]))
        if (startsAt(s, i, lit, n)) return i;
    return -1;
}

void appendCodePoint(QByteArray& out, uint32_t cp) {
    if (cp < 0x80) out += char(cp);
    else if (cp < 0x800) { out += char(0xC0 | cp >> 6); out += char(0x80 | (cp & 63)); }
    else if (cp < 0x10000) { out += char(0xE0 | cp >> 12); out += char(0x80 | (cp >> 6 & 63)); out += char(0x80 | (cp & 63)); }
    else { out += char(0xF0 | cp >> 18); out += char(0x80 | (cp >> 12 & 63)); out += char(0x80 | (cp >> 6 & 63)); out += char(0x80 | (cp & 63)); }
}

}  // namespace

QByteArrayView XmlDoc::localName(QByteArrayView tag) {
    const qsizetype i = tag.indexOf(':');
    return i >= 0 ? tag.sliced(i + 1) : tag;
}

QByteArray XmlDoc::decodeEntities(QByteArrayView s) {
    if (s.indexOf('&') < 0) return QByteArray::fromRawData(s.data(), s.size());
    QByteArray out;
    out.reserve(s.size());
    qsizetype i = 0;
    while (i < s.size()) {
        const char c = s[i];
        if (c != '&') { out += c; ++i; continue; }
        const qsizetype end = findChar(s, i + 1, ';');
        // Längere "Entitäten" gibt es nicht; so bleibt ein lose stehendes & auch in großen Texten billig.
        if (end < 0 || end - i > 12) { out += c; ++i; continue; }
        const QByteArrayView e = s.sliced(i + 1, end - i - 1);
        bool done = false;
        if (e == "lt") { out += '<'; done = true; }
        else if (e == "gt") { out += '>'; done = true; }
        else if (e == "amp") { out += '&'; done = true; }
        else if (e == "quot") { out += '"'; done = true; }
        else if (e == "apos") { out += '\''; done = true; }
        else if (e.size() >= 2 && e[0] == '#') {
            const bool hex = e[1] == 'x';
            const QByteArrayView d = e.sliced(hex ? 2 : 1);
            bool valid = !d.isEmpty();
            uint32_t cp = 0;
            for (const char ch : d) {
                int v = -1;
                if (ch >= '0' && ch <= '9') v = ch - '0';
                else if (hex && ch >= 'a' && ch <= 'f') v = ch - 'a' + 10;
                else if (hex && ch >= 'A' && ch <= 'F') v = ch - 'A' + 10;
                if (v < 0 || cp > 0x10FFFF) { valid = false; break; }
                cp = cp * (hex ? 16 : 10) + uint32_t(v);
            }
            if (valid && cp > 0 && cp <= 0x10FFFF) { appendCodePoint(out, cp); done = true; }
        }
        if (done) i = end + 1;
        else { out += c; ++i; }     // Unbekanntes bleibt wörtlich stehen
    }
    return out;
}

XmlDoc::XmlDoc(const QByteArray& utf8) {
    m_nodes.reserve(size_t(utf8.size() / 64 + 16));
    m_attrs.reserve(size_t(utf8.size() / 32 + 16));
    parse(utf8);
}

void XmlDoc::parse(QByteArrayView src) {
    const qsizetype n = src.size();
    const char* s = src.data();
    qsizetype i = 0;
    std::vector<int32_t> stack;
    stack.reserve(64);
    const auto addText = [&](int32_t node, QByteArrayView text, bool raw) {
        const int32_t t = int32_t(m_texts.size());
        m_texts.push_back({text, raw, -1});
        Node& nd = m_nodes[size_t(node)];
        if (nd.lastText >= 0) m_texts[size_t(nd.lastText)].next = t;
        else nd.firstText = t;
        nd.lastText = t;
    };
    while (i < n) {
        const qsizetype lt = findChar(src, i, '<');
        if (lt < 0) {
            if (!stack.empty()) throw XmlError("Unerwartetes Dateiende");
            break;
        }
        if (!stack.empty() && lt > i) {
            const QByteArrayView t = src.sliced(i, lt - i);
            if (!trimmedView(t).isEmpty()) addText(stack.back(), t, false);
        }
        i = lt;
        if (i + 1 >= n) throw XmlError("Unerwartetes Dateiende");
        const char c1 = s[i + 1];
        if (c1 == '!') {
            if (startsAt(src, i, "<!--", 4)) {
                const qsizetype e = findLit(src, i + 4, "-->", 3);
                if (e < 0) throw XmlError("Kommentar ohne Ende");
                i = e + 3;
                continue;
            }
            if (startsAt(src, i, "<![CDATA[", 9)) {
                const qsizetype e = findLit(src, i + 9, "]]>", 3);
                if (e < 0) throw XmlError("CDATA ohne Ende");
                if (!stack.empty()) addText(stack.back(), src.sliced(i + 9, e - i - 9), true);
                i = e + 3;
                continue;
            }
            int depth = 0;
            qsizetype k = i + 2;
            for (; k < n; ++k) {
                const char c = s[k];
                if (c == '[') ++depth;
                else if (c == ']') --depth;
                else if (c == '>' && depth <= 0) break;
            }
            if (k >= n) throw XmlError("DOCTYPE ohne Ende");
            i = k + 1;
            continue;
        }
        if (c1 == '?') {
            const qsizetype e = findLit(src, i + 2, "?>", 2);
            if (e < 0) throw XmlError("Anweisung ohne Ende");
            i = e + 2;
            continue;
        }
        if (c1 == '/') {
            const qsizetype e = findChar(src, i, '>');
            if (e < 0) throw XmlError("Unerwartetes Dateiende");
            const QByteArrayView name = trimmedView(src.sliced(i + 2, e - i - 2));
            if (stack.empty() || m_nodes[size_t(stack.back())].tag != name) throw XmlError("Schließendes Tag passt nicht");
            stack.pop_back();
            i = e + 1;
            continue;
        }
        qsizetype k = i + 1;
        while (k < n && !isNameEnd(s[k])) ++k;
        if (k == i + 1) throw XmlError("Leeres Tag");
        Node node;
        node.tag = src.sliced(i + 1, k - i - 1);
        node.attrBegin = uint32_t(m_attrs.size());
        bool selfClose = false;
        for (;;) {
            while (k < n && isSpace(s[k])) ++k;
            if (k >= n) throw XmlError("Unerwartetes Dateiende");
            if (s[k] == '>') { ++k; break; }
            if (s[k] == '/' && k + 1 < n && s[k + 1] == '>') { selfClose = true; k += 2; break; }
            const qsizetype nameStart = k;
            while (k < n && !isNameEnd(s[k])) ++k;
            if (k == nameStart) throw XmlError("Ungültiges Attribut");
            const QByteArrayView name = src.sliced(nameStart, k - nameStart);
            while (k < n && isSpace(s[k])) ++k;
            if (k >= n) throw XmlError("Unerwartetes Dateiende");
            if (s[k] != '=') { m_attrs.push_back({name, QByteArrayView()}); continue; }
            ++k;
            while (k < n && isSpace(s[k])) ++k;
            if (k >= n) throw XmlError("Unerwartetes Dateiende");
            const char q = s[k];
            if (q != '"' && q != '\'') throw XmlError("Attribut ohne Anführungszeichen");
            const qsizetype end = findChar(src, k + 1, q);
            if (end < 0) throw XmlError("Attribut ohne Ende");
            m_attrs.push_back({name, src.sliced(k + 1, end - k - 1)});
            k = end + 1;
        }
        node.attrEnd = uint32_t(m_attrs.size());
        if (m_nodes.size() >= MAX_NODES) throw XmlError("Zu viele Elemente");
        const int32_t id = int32_t(m_nodes.size());
        if (stack.empty()) {
            if (m_root >= 0) throw XmlError("Mehr als ein Wurzelelement");
            m_root = id;
        } else {
            Node& parent = m_nodes[size_t(stack.back())];
            if (parent.lastChild >= 0) m_nodes[size_t(parent.lastChild)].nextSibling = id;
            else parent.firstChild = id;
            parent.lastChild = id;
        }
        m_nodes.push_back(node);
        if (!selfClose) {
            if (int(stack.size()) >= MAX_DEPTH) throw XmlError("Zu tief verschachtelt");
            stack.push_back(id);
        }
        i = k;
    }
    if (!stack.empty()) throw XmlError("Tag wird nicht geschlossen");
    if (m_root < 0) throw XmlError("Kein XML gefunden");
}

QByteArrayView XmlDoc::rawAttr(int n, QByteArrayView name) const {
    const Node& nd = m_nodes[size_t(n)];
    for (uint32_t a = nd.attrEnd; a > nd.attrBegin; --a)
        if (m_attrs[a - 1].name == name) return m_attrs[a - 1].value;
    return {};
}
bool XmlDoc::hasAttr(int n, QByteArrayView name) const {
    const Node& nd = m_nodes[size_t(n)];
    for (uint32_t a = nd.attrBegin; a < nd.attrEnd; ++a) if (m_attrs[a].name == name) return true;
    return false;
}
QByteArray XmlDoc::attr(int n, QByteArrayView name) const { return decodeEntities(rawAttr(n, name)); }

QByteArray XmlDoc::text(int n) const {
    QByteArray out;
    for (int32_t t = m_nodes[size_t(n)].firstText; t >= 0; t = m_texts[size_t(t)].next) {
        const Text& part = m_texts[size_t(t)];
        if (part.raw) out.append(part.text.data(), part.text.size());
        else out += decodeEntities(part.text);
    }
    return out;
}
int XmlDoc::child(int n, QByteArrayView tag) const {
    for (int32_t c = m_nodes[size_t(n)].firstChild; c >= 0; c = m_nodes[size_t(c)].nextSibling)
        if (m_nodes[size_t(c)].tag == tag) return c;
    return -1;
}
std::vector<int> XmlDoc::allByLocalName(QByteArrayView local) const {
    std::vector<int> out;
    for (size_t i = 0; i < m_nodes.size(); ++i) if (localName(m_nodes[i].tag) == local) out.push_back(int(i));
    return out;
}

}  // namespace lumacut::import
