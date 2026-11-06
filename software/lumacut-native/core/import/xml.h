#pragma once
/**
 * Kleiner, schneller XML-Leser wie src/core/import/xml.ts: flache Knotenliste, Attribute als Sichten in den Puffer,
 * also nichts kopiert. Nicht namensraumbewusst (Tags behalten ihr Präfix). DOCTYPE wird übersprungen, eigene Entitäten
 * werden nie aufgelöst: keine Datei kann etwas nachladen oder sich aufblähen. Verschachtelung ist begrenzt.
 */
#include <QByteArray>
#include <QByteArrayView>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace lumacut::import {

class XmlError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class XmlDoc {
public:
    static constexpr int MAX_DEPTH = 256;
    static constexpr size_t MAX_NODES = 20'000'000;

    struct Node {
        QByteArrayView tag;
        uint32_t attrBegin = 0, attrEnd = 0;
        int32_t firstChild = -1, lastChild = -1, nextSibling = -1;
        int32_t firstText = -1, lastText = -1;
    };
    struct Attr {
        QByteArrayView name, value;
    };
    struct Text {
        QByteArrayView text;
        bool raw = false;       /// CDATA
        int32_t next = -1;
    };

    /** utf8 muss leben, solange das Dokument lebt (Sichten). Wirft XmlError. */
    explicit XmlDoc(const QByteArray& utf8);

    int root() const { return m_root; }
    const Node& node(int i) const { return m_nodes[size_t(i)]; }
    size_t nodeCount() const { return m_nodes.size(); }

    /** Roher Wert ohne Entitäten-Auflösung, leer wenn nicht vorhanden; bei doppelten gilt der letzte. */
    QByteArrayView rawAttr(int n, QByteArrayView name) const;
    bool hasAttr(int n, QByteArrayView name) const;
    /** Wert mit aufgelösten Entitäten. Ohne '&' keine Kopie (nur gültig wie der Puffer). */
    QByteArray attr(int n, QByteArrayView name) const;
    /** Zusammengesetzter Text des Knotens, Entitäten aufgelöst. */
    QByteArray text(int n) const;
    /** Erstes Kind mit genau diesem Tag, sonst -1. */
    int child(int n, QByteArrayView tag) const;
    /** Alle Knoten mit diesem lokalen Namen in Dokumentreihenfolge. */
    std::vector<int> allByLocalName(QByteArrayView local) const;

    static QByteArrayView localName(QByteArrayView tag);
    static QByteArray decodeEntities(QByteArrayView s);

private:
    void parse(QByteArrayView src);
    std::vector<Node> m_nodes;
    std::vector<Attr> m_attrs;
    std::vector<Text> m_texts;
    int m_root = -1;
};

inline QByteArrayView trimmedView(QByteArrayView s) {
    const auto space = [](char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'; };
    qsizetype a = 0, b = s.size();
    while (a < b && space(s[a])) ++a;
    while (b > a && space(s[b - 1])) --b;
    return s.sliced(a, b - a);
}

}  // namespace lumacut::import
