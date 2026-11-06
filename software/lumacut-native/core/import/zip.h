#pragma once
/** Kleiner ZIP-Leser (gespeichert und Deflate) über das zentrale Verzeichnis, mit Grenzen gegen aufgeblähte Archive. */
#include <QByteArray>
#include <QHash>
#include <QString>
#include <QStringList>

namespace lumacut::import {

inline bool isZip(const QByteArray& b) { return b.size() >= 22 && b[0] == 'P' && b[1] == 'K'; }
/** Namen aller Einträge. Wirft ImportError, wenn es kein ZIP ist. */
QStringList zipNames(const QByteArray& b);
/** Alle Dateien. Wirft ImportError (kaputt oder zu groß). */
QHash<QString, QByteArray> readZip(const QByteArray& b);
/** Rohes Deflate (RFC 1951) mit Obergrenze. Wirft ImportError. */
QByteArray inflateRaw(const char* data, qsizetype size, qsizetype limit);

}  // namespace lumacut::import
