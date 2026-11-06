#include "Fmt.h"
#include <QDateTime>
#include <QLocale>
#include <cmath>

bool Fmt::isNumber(const QVariant& v) {
    if (!v.isValid() || v.isNull()) return false;
    bool ok = false;
    const double d = v.toDouble(&ok);
    return ok && std::isfinite(d);
}
QString Fmt::de(const QVariant& v, int digits) {
    if (!isNumber(v)) return QStringLiteral("–");
    static const QLocale german(QLocale::German, QLocale::Germany);
    QLocale l = german;
    l.setNumberOptions(QLocale::OmitGroupSeparator);
    return l.toString(v.toDouble(), 'f', digits);
}
QString Fmt::trim(const QVariant& v, int digits) {
    QString s = de(v, digits);
    if (digits > 0 && s.contains(u',')) {
        while (s.endsWith(u'0')) s.chop(1);
        if (s.endsWith(u',')) s.chop(1);
    }
    return s == QStringLiteral("-0") ? QStringLiteral("0") : s;
}
double Fmt::parse(const QString& text) {
    QString t = text.trimmed();
    t.replace(u',', u'.');
    bool ok = false;
    const double d = t.toDouble(&ok);
    return ok ? d : std::nan("");
}
QString Fmt::when(const QVariant& v) {
    if (!v.isValid() || v.isNull() || v.toString().isEmpty()) return QStringLiteral("–");
    QDateTime d;
    if (v.typeId() == QMetaType::QString) {
        d = QDateTime::fromString(v.toString(), Qt::ISODateWithMs);
        if (!d.isValid()) return v.toString();
    } else {
        const double n = v.toDouble();
        d = QDateTime::fromMSecsSinceEpoch(qint64(n < 1e11 ? n * 1000 : n));
    }
    return d.toLocalTime().toString(QStringLiteral("dd.MM.yyyy, HH:mm"));
}
