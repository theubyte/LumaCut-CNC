#pragma once
#include <QJSValue>
#include <QObject>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

struct PiReply;

/**
 * The Pi's material database. The Pi is the source; only a copy for the time without connection stays here, and that
 * copy cannot be changed. Every write names the revision it builds on (409 = reload, ask again).
 * Items and groups are plain maps with the Pi's fields; a group is {key, name, thicknessMm, entries: [...]}.
 */
class Materials : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Materials)
    Q_PROPERTY(QVariantList items READ items NOTIFY changed)
    Q_PROPERTY(int revision READ revision NOTIFY changed)
    Q_PROPERTY(bool fromPi READ fromPi NOTIFY changed)
    Q_PROPERTY(bool loading READ loading NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
public:
    explicit Materials(QObject* parent);
    QVariantList items() const { return m_items; }
    int revision() const { return m_rev; }
    bool fromPi() const { return m_fromPi; }
    bool loading() const { return m_loading; }
    QString error() const { return m_error; }

    Q_INVOKABLE void load();
    /** One physical material (name and thickness) with its processes, sorted; optional filter on name or process. */
    Q_INVOKABLE QVariantList groups(const QString& query = {}) const;
    Q_INVOKABLE static QString groupKey(const QString& name, double thicknessMm);
    /** The entry for a process in a group, or an empty map. */
    Q_INVOKABLE static QVariantMap entryOf(const QVariantMap& group, const QString& process);
    /** Passes from thickness / depth per pass when set, otherwise the stored passes. */
    Q_INVOKABLE static int effectivePasses(const QVariantMap& material);
    Q_INVOKABLE static QVariantMap newProcess(const QString& name, double thickness, const QString& process);
    Q_INVOKABLE static bool lowPower(const QVariantMap& material);
    Q_INVOKABLE static bool focusDropOk(int passes, double zStep);
    /** {x, y, clean, label}[] in 0..1 for the tone curve chart, sorted by energy; empty below two points. */
    Q_INVOKABLE static QVariantList tonePoints(const QVariantMap& material);

    using Done = std::function<void(bool ok, const QVariantMap& material, const QString& error)>;
    void create(const QVariantMap& m, Done done);
    void update(const QString& id, const QVariantMap& patch, Done done);
    void remove(const QString& id, Done done);

    // QML, errors end up as toast. cb(ok) optional.
    Q_INVOKABLE void addProcess(const QString& name, double thickness, const QString& process);
    Q_INVOKABLE void patch(const QString& id, const QVariantMap& fields);
    Q_INVOKABLE void removeEntry(const QString& id);
    /** New material with these processes (comma-separated), one after the other. cb(ok, groupKey). */
    Q_INVOKABLE void createGroup(const QString& name, double thickness, const QString& processes, const QJSValue& cb);
    /** New name and thickness for all processes of a group, and for the current material if it is this one. cb(ok, groupKey). */
    Q_INVOKABLE void renameGroup(const QVariantMap& group, const QString& name, double thickness, const QJSValue& cb);
    Q_INVOKABLE void removeGroup(const QVariantMap& group, const QJSValue& cb);
    /** Dieses Material verwenden: current material on the Pi, then useGroup(group) for whoever holds the layers. */
    Q_INVOKABLE void use(const QVariantMap& group);
signals:
    void changed();
    /** The layers should take this group's values (applyGroupToDoc). Emitted by use(), and by reapply() from the view. */
    void applyToLayers(const QVariantMap& group);
private:
    void write(const QString& what, const std::function<void(int rev, std::function<void(const PiReply&)>)>& fn, Done done);
    void saveCache();
    QVariantList m_items;
    int m_rev = 0;
    bool m_fromPi = false;
    bool m_loading = false;
    QString m_error;
};
