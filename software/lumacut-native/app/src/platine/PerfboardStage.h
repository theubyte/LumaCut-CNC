#pragma once
#include <QColor>
#include <QtQml/qqmlregistration.h>
#include <vector>
#include "gpu/StageItem.h"

/**
 * GPU view of the perfboard editor: board, pads, holes, part bodies, connections, the real laser markings (pads left
 * out), selection, the ghost while placing and the assistant's highlight. Left mouse edits through the Perfboard
 * singleton, right or middle mouse pans, the wheel zooms. "Von unten" mirrors the view about the board's vertical axis.
 */
class PerfboardStage : public StageItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QColor boardColor MEMBER m_board NOTIFY colorsChanged)
    Q_PROPERTY(QColor padColor MEMBER m_pad NOTIFY colorsChanged)
    Q_PROPERTY(QColor holeColor MEMBER m_hole NOTIFY colorsChanged)
    Q_PROPERTY(QColor bodyColor MEMBER m_body NOTIFY colorsChanged)
    Q_PROPERTY(QColor solderColor MEMBER m_solder NOTIFY colorsChanged)
    Q_PROPERTY(QColor wireColor MEMBER m_wire NOTIFY colorsChanged)
    Q_PROPERTY(QColor laserColor MEMBER m_laser NOTIFY colorsChanged)
    Q_PROPERTY(QColor accentColor MEMBER m_accent NOTIFY colorsChanged)
    Q_PROPERTY(QColor warnColor MEMBER m_warn NOTIFY colorsChanged)
    Q_PROPERTY(int viewRevision READ viewRevision NOTIFY viewRevisionChanged)   // bump to re-place QML labels
    Q_PROPERTY(int shownElements READ shownElements NOTIFY viewRevisionChanged)
public:
    explicit PerfboardStage(QQuickItem* parent = nullptr);
    int viewRevision() const { return m_viewRev; }
    int shownElements() const { return m_shown; }

    /** Board mm to item px, honouring the view from below. */
    Q_INVOKABLE QPointF boardToItem(double x, double y) const;
    Q_INVOKABLE QPointF holeItemPos(int c, int r) const;
    Q_INVOKABLE void fitBoard();

signals:
    void colorsChanged();
    void viewRevisionChanged();

protected:
    void mousePressEvent(QMouseEvent* e) override;
    void mouseMoveEvent(QMouseEvent* e) override;
    void mouseReleaseEvent(QMouseEvent* e) override;
    void hoverMoveEvent(QHoverEvent* e) override;
    void keyPressEvent(QKeyEvent* e) override;

private:
    void rebuildStatic();
    void rebuildDynamic();
    void restyle();
    QPointF toBoard(QPointF itemPos) const;
    QTransform boardTransform() const;

    bool m_panning = false, m_editing = false;
    double m_w = 0, m_h = 0;
    int m_viewRev = 0, m_shown = 0;
    std::vector<quint64> m_dynamicIds;
    QColor m_board{0x1f, 0x7a, 0x52}, m_pad{0xd4, 0xd6, 0xdc}, m_hole{0x20, 0x20, 0x24}, m_body{0xf3, 0xf1, 0xe6},
           m_solder{0xe6, 0x97, 0x5c}, m_wire{0x6c, 0xb6, 0xff}, m_laser{0x8f, 0x9b, 0xff}, m_accent{0x4a, 0x57, 0xe3}, m_warn{0xf2, 0xb4, 0x5c};
};
