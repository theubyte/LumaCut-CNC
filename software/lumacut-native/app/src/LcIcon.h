#pragma once
#include <QColor>
#include <QQuickPaintedItem>
#include <QtQml/qqmlregistration.h>

/** Line icon from the Lucide table: LcIcon { name: "fan"; size: 16; color: Theme.muted; strokeWidth: 2 }. */
class LcIcon : public QQuickPaintedItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString name READ name WRITE setName NOTIFY changed)
    Q_PROPERTY(QColor color READ color WRITE setColor NOTIFY changed)
    Q_PROPERTY(int size READ size WRITE setSize NOTIFY changed)
    Q_PROPERTY(qreal strokeWidth READ strokeWidth WRITE setStrokeWidth NOTIFY changed)
public:
    explicit LcIcon(QQuickItem* parent = nullptr);
    void paint(QPainter* painter) override;
    QString name() const { return m_name; }
    void setName(const QString& v);
    QColor color() const { return m_color; }
    void setColor(const QColor& v);
    int size() const { return m_size; }
    void setSize(int v);
    qreal strokeWidth() const { return m_stroke; }
    void setStrokeWidth(qreal v);
signals:
    void changed();
private:
    QString m_name;
    QColor m_color = Qt::black;
    int m_size = 16;
    qreal m_stroke = 2;
};
