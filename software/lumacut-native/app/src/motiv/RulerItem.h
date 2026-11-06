#pragma once
#include <QColor>
#include <QFont>
#include <QQuickPaintedItem>
#include <QtQml/qqmlregistration.h>

/**
 * One ruler beside the stage: ticks and whole-number labels in mm that follow zoom and pan. Painted once per view change
 * into a small texture. RulerItem { vertical: true; zoom: stage.effectiveZoom; pan: stage.pan.y }
 * selFrom/selTo in mm draw the selection's extent as a soft band.
 */
class RulerItem : public QQuickPaintedItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool vertical MEMBER m_vertical NOTIFY changed)
    Q_PROPERTY(qreal zoom MEMBER m_zoom NOTIFY changed)
    Q_PROPERTY(qreal pan MEMBER m_pan NOTIFY changed)
    Q_PROPERTY(qreal offset MEMBER m_offset NOTIFY changed)   // item px from the ruler's start to the stage's start
    Q_PROPERTY(bool hasSel MEMBER m_hasSel NOTIFY changed)
    Q_PROPERTY(qreal selFrom MEMBER m_selFrom NOTIFY changed)
    Q_PROPERTY(qreal selTo MEMBER m_selTo NOTIFY changed)
    Q_PROPERTY(QColor tickColor MEMBER m_tick NOTIFY changed)
    Q_PROPERTY(QColor textColor MEMBER m_text NOTIFY changed)
    Q_PROPERTY(QColor bandColor MEMBER m_band NOTIFY changed)
    Q_PROPERTY(QFont font MEMBER m_font NOTIFY changed)
public:
    explicit RulerItem(QQuickItem* parent = nullptr);
    void paint(QPainter* p) override;
signals:
    void changed();
private:
    bool m_vertical = false, m_hasSel = false;
    qreal m_zoom = 1, m_pan = 0, m_offset = 0, m_selFrom = 0, m_selTo = 0;
    QColor m_tick, m_text, m_band;
    QFont m_font;
};
