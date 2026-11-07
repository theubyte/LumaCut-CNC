#pragma once
#include <QJSValue>
#include <QObject>
#include <QSet>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

/**
 * The ONE way the app triggers machine actions (docs/STAND.md §4). Every laser or motion job needs an explicit go,
 * "Hände raus, Deckel zu, Brille". Exempt: single jog steps, light, exhaust, abort, NOT-AUS.
 * Ops that are neither gated nor free are refused, so a new op cannot slip through. Service ops that fire the laser
 * directly are deliberately not offered.
 *
 * QML:  MachineActions.run("probe", {}, {}, function(ok, reply) {...})
 *       opts: { go: {title, detail, okLabel, kind}, quiet: bool, timeoutMs: int }
 *       cb gets ok = false when the operator said no (reply null) or the Pi refused (toast already shown).
 * C++:  MachineActions::instance()->run(op, fields, opts, [](bool ok, const QVariantMap& reply) {...});
 */
class MachineActions : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(MachineActions)
    Q_PROPERTY(bool goOpen READ goOpen NOTIFY goChanged)
    Q_PROPERTY(QString goTitle READ goTitle NOTIFY goChanged)
    Q_PROPERTY(QString goDetail READ goDetail NOTIFY goChanged)
    Q_PROPERTY(QString goKind READ goKind NOTIFY goChanged)          // move, laser
    Q_PROPERTY(QString goOkLabel READ goOkLabel NOTIFY goChanged)
    /** The op waiting for an answer or running in the views, "" when none. */
    Q_PROPERTY(QString busyOp READ busyOp NOTIFY busyChanged)
    Q_PROPERTY(QString jogActive READ jogActive NOTIFY busyChanged)
    Q_PROPERTY(double jogStep READ jogStep WRITE setJogStep NOTIFY jogStepChanged)
public:
    using Done = std::function<void(bool ok, const QVariantMap& reply)>;
    explicit MachineActions(QObject* parent);

    void run(const QString& op, const QVariantMap& fields, const QVariantMap& opts, Done done);
    Q_INVOKABLE void run(const QString& op, const QVariantMap& fields = {}, const QVariantMap& opts = {}, const QJSValue& cb = {});
    /** Ask for the go directly, before several steps that belong together. */
    void askGo(const QVariantMap& request, std::function<void(bool)> cb);
    /**
     * One step of a series the operator already said yes to with askGo (the camera scan: one go, many moves).
     * Only a known gated op; never call it without that answer.
     */
    void runApproved(const QString& op, const QVariantMap& fields, const QVariantMap& opts, Done done);
    Q_INVOKABLE void askGo(const QVariantMap& request, const QJSValue& cb);
    Q_INVOKABLE void answerGo(bool yes);
    Q_INVOKABLE static bool isAllowed(const QString& op);
    Q_INVOKABLE static bool needsGo(const QString& op);

    /** Referenzfahrt, with the question whether the head stands free when the Pi does not know its height. */
    Q_INVOKABLE void home();
    /** One jog step as seen from the door: left, right, up, down, zup, zdown. Single steps only, next one after the Pi answered. */
    Q_INVOKABLE void jog(const QString& dir);
    /** NOT-AUS: no gate, short timeout, sent a second time if the first attempt fails. */
    Q_INVOKABLE void estop();
    /** Zu Position fahren, in work coordinates. */
    Q_INVOKABLE void moveTo(double workX, double workY);

    bool goOpen() const { return bool(m_goCb); }
    QString goTitle() const { return m_go.value("title").toString(); }
    QString goDetail() const { return m_go.value("detail").toString(); }
    QString goKind() const { return m_go.value("kind").toString(); }
    QString goOkLabel() const;
    QString busyOp() const { return m_busy; }
    QString jogActive() const { return m_jog; }
    double jogStep() const { return m_jogStep; }
    void setJogStep(double v);
signals:
    void goChanged();
    void busyChanged();
    void jogStepChanged();
private:
    void send(const QString& op, const QVariantMap& fields, const QVariantMap& opts, Done done);
    QVariantMap m_go;
    std::function<void(bool)> m_goCb;
    QString m_busy;
    QString m_jog;
    double m_jogStep = 1;
};
