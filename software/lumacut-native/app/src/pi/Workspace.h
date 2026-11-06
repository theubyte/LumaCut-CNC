#pragma once
#include <QJSValue>
#include <QObject>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

/**
 * The shared working state on the Pi ("Arbeitsstand"). The current material lives here: no job starts without it,
 * because its thickness sets the travel height. The object follows status.sync by itself.
 */
class Workspace : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Workspace)
    Q_PROPERTY(bool hasMaterial READ hasMaterial NOTIFY changed)
    Q_PROPERTY(QString materialName READ materialName NOTIFY changed)
    Q_PROPERTY(double materialThickness READ materialThickness NOTIFY changed)
    Q_PROPERTY(int revision READ revision NOTIFY changed)
    Q_PROPERTY(int scanRevision READ scanRevision NOTIFY changed)
    Q_PROPERTY(QVariantList areas READ areas NOTIFY changed)
    Q_PROPERTY(QVariantList probePoints READ probePoints NOTIFY changed)
public:
    using Done = std::function<void(bool ok, const QString& error)>;
    explicit Workspace(QObject* parent);
    bool hasMaterial() const { return !m_material.isEmpty(); }
    QString materialName() const { return m_material.value("name").toString(); }
    double materialThickness() const { return m_material.value("thickness_mm").toDouble(); }
    int revision() const { return m_rev; }
    int scanRevision() const { return m_scanRev; }
    QVariantList areas() const { return m_areas; }
    QVariantList probePoints() const { return m_points; }
    void load(Done done = {});
    /** Writes fields on top of what the Pi has. A change from another device in between is taken first, then this one goes on top. */
    void save(const QVariantMap& fields, Done done);
    void setMaterial(const QString& name, double thicknessMm, Done done);
signals:
    void changed();
private:
    void take(const QVariantMap& w);
    QVariantMap m_material;
    QVariantList m_areas, m_points;
    int m_rev = -1;
    int m_scanRev = 0;
    bool m_loading = false;
};
