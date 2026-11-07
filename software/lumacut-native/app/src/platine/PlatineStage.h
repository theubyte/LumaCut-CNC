#pragma once
#include <QColor>
#include <QtQml/qqmlregistration.h>
#include <memory>
#include "gpu/StageItem.h"

namespace lumacut::pcb { struct Plan; struct Board; }

/**
 * GPU preview of the board as it lies under the laser: board, copper, laser paths, holes, marks, mask, silk, outline,
 * each a StageItem layer that can be hidden without new geometry. Fed from the Platine singleton. The sheet is the job
 * area plus a small margin; wheel zooms, dragging pans.
 */
class PlatineStage : public StageItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QColor boardColor MEMBER m_board NOTIFY colorsChanged)
    Q_PROPERTY(QColor copperColor MEMBER m_copper NOTIFY colorsChanged)
    Q_PROPERTY(QColor laserColor MEMBER m_laser NOTIFY colorsChanged)
    Q_PROPERTY(QColor drillColor MEMBER m_drill NOTIFY colorsChanged)
    Q_PROPERTY(QColor markColor MEMBER m_mark NOTIFY colorsChanged)
    Q_PROPERTY(QColor maskColor MEMBER m_mask NOTIFY colorsChanged)
    Q_PROPERTY(QColor silkColor MEMBER m_silk NOTIFY colorsChanged)
    Q_PROPERTY(QColor edgeColor MEMBER m_edgeLine NOTIFY colorsChanged)
    Q_PROPERTY(QColor badColor MEMBER m_bad NOTIFY colorsChanged)
    Q_PROPERTY(int shownElements READ shownElements NOTIFY contentChanged)   // for tests
public:
    explicit PlatineStage(QQuickItem* parent = nullptr);
    int shownElements() const { return m_shown; }

signals:
    void colorsChanged();
    void contentChanged();

private:
    void rebuild();
    void restyle();

    std::shared_ptr<const lumacut::pcb::Plan> m_lastPlan;
    std::shared_ptr<const lumacut::pcb::Board> m_lastBoard;
    bool m_lastMirror = false;
    int m_lastSide = -1;
    int m_shown = 0;
    double m_lastW = 0, m_lastH = 0;
    QColor m_board{0xdc, 0xd6, 0xbd}, m_copper{0xc9, 0x74, 0x3a}, m_laser{0x4a, 0x57, 0xe3}, m_drill{0x5b, 0x61, 0x78},
           m_mark{0xb2, 0x3f, 0xb0}, m_mask{0x1c, 0x9a, 0x78}, m_silk{0x2f, 0x33, 0x42}, m_edgeLine{0x7a, 0x80, 0x97}, m_bad{0xcf, 0x33, 0x40};
};
