#pragma once
#include <QHash>
#include <QObject>
#include <QPointer>
#include <QQuickItem>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include <optional>
#include "Singleton.h"
#include "core/werkstatt/generators.h"

class StageItem;

/**
 * The workshop: generators as data (form description, defaults, compute), the live result of the open one and the
 * step that puts it into the project. Nothing here talks to the machine. QML: Workshop.
 *
 *   Workshop.tool = "box"; Workshop.setParam("w", 120)    // recomputes shortly after
 *   Workshop.attachPreview(stage)                          // a Stage item shows the result on the bed
 *   Workshop.apply()                                       // one undo step, onto the active plate (or a fresh one)
 */
class Workshop : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Workshop)
    Q_PROPERTY(QVariantList tools READ tools CONSTANT)
    Q_PROPERTY(QString tool READ tool WRITE setTool NOTIFY toolChanged)
    Q_PROPERTY(QVariantMap toolInfo READ toolInfo NOTIFY toolChanged)
    Q_PROPERTY(QVariantMap params READ params NOTIFY paramsChanged)
    Q_PROPERTY(QVariantList fields READ fields NOTIFY fieldsChanged)
    Q_PROPERTY(QVariantMap result READ result NOTIFY resultChanged)
    Q_PROPERTY(int previewPlate READ previewPlate WRITE setPreviewPlate NOTIFY resultChanged)
public:
    explicit Workshop(QObject* parent);

    QVariantList tools() const;
    QString tool() const { return m_tool; }
    void setTool(const QString& id);
    QVariantMap toolInfo() const;
    QVariantMap params() const { return m_params.value(m_tool); }
    QVariantList fields() const { return m_fields; }
    QVariantMap result() const { return m_info; }
    int previewPlate() const { return m_plate; }
    void setPreviewPlate(int p);

    Q_INVOKABLE void setParam(const QString& key, const QVariant& value);
    Q_INVOKABLE void resetParams();
    /** Computes now instead of shortly after (tests, the apply button). */
    Q_INVOKABLE void recompute();
    Q_INVOKABLE void attachPreview(QQuickItem* stage);
    Q_INVOKABLE void fitPreview();
    /** Puts the current result into the project. {ok, count, plates, firstPlate} or {ok: false, error}. */
    Q_INVOKABLE QVariantMap apply();

signals:
    void toolChanged();
    void paramsChanged();
    /** Only when the form itself changes, so typing never rebuilds the field being typed in. */
    void fieldsChanged();
    void resultChanged();

private:
    struct Tool {
        QString id, group, title, blurb, icon;
        bool compute = true;   // false: only explains (photo)
        std::function<QVariantMap()> defaults;
        std::function<QVariantList(const QVariantMap&)> fields;
        std::function<lumacut::Werkstatt::GenResult(const QVariantMap&)> run;
    };
    void buildTools();
    const Tool* current() const;
    void showPreview();
    void syncFields();
    std::optional<lumacut::Box> motifBox() const;
    lumacut::PolySet shape(const QString& text, double h, bool bold);

    std::vector<Tool> m_list;
    QString m_tool;
    QHash<QString, QVariantMap> m_params;
    std::optional<lumacut::Werkstatt::GenResult> m_res;
    QVariantMap m_info;
    QVariantList m_fields;
    int m_plate = 0;
    QPointer<StageItem> m_stage;
    QTimer m_timer;
    QHash<QString, lumacut::PolySet> m_textCache;
};
