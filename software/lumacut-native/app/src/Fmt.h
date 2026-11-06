#pragma once
#include <QObject>
#include <QVariant>
#include <QtQml/qqmlregistration.h>
#include "Singleton.h"

/** German number and date text, one place for the whole app. */
class Fmt : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Fmt)
public:
    explicit Fmt(QObject* parent) : QObject(parent) {}
    /** Fixed digits, decimal comma, "–" when there is no number. */
    Q_INVOKABLE static QString de(const QVariant& v, int digits = 1);
    /** At most `digits`, no trailing zeros: 0,5 / 12 / 0,125. */
    Q_INVOKABLE static QString trim(const QVariant& v, int digits = 2);
    /** Accepts comma and point. NaN when unreadable. */
    Q_INVOKABLE static double parse(const QString& text);
    /** ISO text or seconds since 1970 as "06.11.2026, 19:37"; "–" when empty. */
    Q_INVOKABLE static QString when(const QVariant& v);
    Q_INVOKABLE static bool isNumber(const QVariant& v);
};
