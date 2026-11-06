#pragma once
#include <QJSValue>
#include <QObject>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

/** Toast.show("Text", "ok") from QML, Toast::instance()->show(...) from C++. Tones: ok, bad, warn, info. */
class Toast : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Toast)
    Q_PROPERTY(QVariantList items READ items NOTIFY itemsChanged)
    Q_PROPERTY(QString lastText READ lastText NOTIFY itemsChanged)
public:
    explicit Toast(QObject* parent) : QObject(parent) {}
    Q_INVOKABLE void show(const QString& text, const QString& tone = QStringLiteral("info"));
    Q_INVOKABLE void dismiss(int id);
    QVariantList items() const { return m_items; }
    QString lastText() const { return m_last; }
signals:
    void itemsChanged();
private:
    QVariantList m_items;
    QString m_last;
    int m_next = 0;
};

/** Plain question, never a go: Confirm.ask({title, body, okLabel, danger}, function(yes) {...}). */
class Confirm : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Confirm)
    Q_PROPERTY(bool open READ open NOTIFY changed)
    Q_PROPERTY(QString title READ title NOTIFY changed)
    Q_PROPERTY(QString body READ body NOTIFY changed)
    Q_PROPERTY(QString okLabel READ okLabel NOTIFY changed)
    Q_PROPERTY(bool danger READ danger NOTIFY changed)
public:
    explicit Confirm(QObject* parent) : QObject(parent) {}
    Q_INVOKABLE void ask(const QVariantMap& request, const QJSValue& callback);
    void askNative(const QVariantMap& request, std::function<void(bool)> callback);
    Q_INVOKABLE void answer(bool yes);
    bool open() const { return bool(m_cb); }
    QString title() const { return m_req.value("title").toString(); }
    QString body() const { return m_req.value("body").toString(); }
    QString okLabel() const { const QString s = m_req.value("okLabel").toString(); return s.isEmpty() ? QStringLiteral("OK") : s; }
    bool danger() const { return m_req.value("danger").toBool(); }
signals:
    void changed();
private:
    QVariantMap m_req;
    std::function<void(bool)> m_cb;
};
