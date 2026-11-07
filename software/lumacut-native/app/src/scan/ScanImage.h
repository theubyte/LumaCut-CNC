#pragma once
#include <QImage>
#include <QQuickItem>
#include <QtQml/qqmlregistration.h>

/**
 * Shows a camera picture as a GPU texture: source "background" (the scan, stretched over the item, which QML lays
 * over the bed) or "live" (the latest head-camera picture, aspect-fit). Follows Editor and Scanner by itself.
 *   ScanImage { source: "live" }
 */
class ScanImage : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString source READ source WRITE setSource NOTIFY sourceChanged)
    Q_PROPERTY(bool hasImage READ hasImage NOTIFY imageChanged)
    Q_PROPERTY(QSizeF imageSize READ imageSize NOTIFY imageChanged)
public:
    explicit ScanImage(QQuickItem* parent = nullptr);
    QString source() const { return m_source; }
    void setSource(const QString& s);
    bool hasImage() const { return !m_image.isNull(); }
    QSizeF imageSize() const { return m_image.size(); }
signals:
    void sourceChanged();
    void imageChanged();
protected:
    QSGNode* updatePaintNode(QSGNode* old, UpdatePaintNodeData*) override;
    void geometryChange(const QRectF& n, const QRectF& o) override { QQuickItem::geometryChange(n, o); update(); }
private:
    void pull();
    QString m_source = QStringLiteral("live");
    QImage m_image;
    bool m_dirty = false;
};
