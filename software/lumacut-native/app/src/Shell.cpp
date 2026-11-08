#include "Shell.h"
#include "AppSettings.h"
#include <QKeyEvent>
#include <QMetaObject>
#include <QMouseEvent>
#include <QQuickWindow>

static const QStringList kDests = {"material", "motiv", "start", "platine", "werkstatt", "maschine", "optionen", "papier"};

Shell::Shell(QObject* parent) : QObject(parent) {
    const QString d = AppSettings::instance()->value("dest", "motiv").toString();
    m_dest = kDests.contains(d) ? d : QStringLiteral("motiv");
}
void Shell::navigate(const QString& key) {
    if (!kDests.contains(key) || key == m_dest) return;
    m_dest = key;
    AppSettings::instance()->setValue("dest", key);
    emit destChanged();
}
void Shell::pushModal(QQuickItem* item) {
    m_modals.removeAll(item);
    m_modals.append(item);
    emit modalChanged();
}
void Shell::popModal(QQuickItem* item) {
    if (m_modals.removeAll(item)) emit modalChanged();
}
void Shell::attachWindow(QQuickWindow* window) {
    if (m_window) m_window->removeEventFilter(this);
    m_window = window;
    if (window) window->installEventFilter(this);
}
bool Shell::typing() const {
    auto* f = m_window ? m_window->activeFocusItem() : nullptr;
    return f && (f->inherits("QQuickTextInput") || f->inherits("QQuickTextEdit"));
}

static void collectTabStops(QQuickItem* item, QList<QQuickItem*>& out) {
    if (!item->isVisible() || !item->isEnabled()) return;
    if (item->activeFocusOnTab()) out.append(item);
    const auto children = item->childItems();
    for (auto* c : children) collectTabStops(c, out);
}
void Shell::cycleFocus(bool back) {
    while (!m_modals.isEmpty() && !m_modals.last()) m_modals.removeLast();
    if (m_modals.isEmpty()) return;
    QList<QQuickItem*> stops;
    collectTabStops(m_modals.last(), stops);
    if (stops.isEmpty()) return;
    const int at = stops.indexOf(m_window->activeFocusItem());
    const int n = stops.size();
    const int next = at < 0 ? 0 : (at + (back ? n - 1 : 1)) % n;
    stops[next]->forceActiveFocus(back ? Qt::BacktabFocusReason : Qt::TabFocusReason);
}

bool Shell::eventFilter(QObject* watched, QEvent* event) {
    if (watched != m_window) return QObject::eventFilter(watched, event);
    if (event->type() == QEvent::MouseButtonPress) {
        // A click outside a text field ends the input, like everywhere on Windows: LcNumber commits before the click lands.
        auto* f = m_window->activeFocusItem();
        if (f && (f->inherits("QQuickTextInput") || f->inherits("QQuickTextEdit"))) {
            const QPointF p = static_cast<QMouseEvent*>(event)->scenePosition();
            if (!f->contains(f->mapFromScene(p))) m_window->contentItem()->forceActiveFocus(Qt::MouseFocusReason);
        }
        return false;
    }
    if (event->type() != QEvent::KeyPress) return false;
    auto* e = static_cast<QKeyEvent*>(event);
    const int key = e->key();
    const auto mods = e->modifiers() & (Qt::ControlModifier | Qt::AltModifier | Qt::ShiftModifier | Qt::MetaModifier);
    // NOT-AUS first, from anywhere, also while typing and over dialogs.
    if (key == Qt::Key_Pause) { if (!e->isAutoRepeat()) emit estopKey(); return true; }
    if (!m_modals.isEmpty()) {
        if (key == Qt::Key_Escape) {
            if (auto top = m_modals.last()) QMetaObject::invokeMethod(top, "requestClose");
            return true;
        }
        if (key == Qt::Key_Tab || key == Qt::Key_Backtab) { cycleFocus(key == Qt::Key_Backtab || (mods & Qt::ShiftModifier)); return true; }
        if (mods == Qt::AltModifier && key == Qt::Key_S) { emit goKey(); return true; }
        return false;
    }
    if (mods == Qt::ControlModifier && key == Qt::Key_7) { navigate(QStringLiteral("papier")); return true; }
    if (mods == Qt::ControlModifier && key >= Qt::Key_1 && key <= Qt::Key_6) {
        navigate(kDests[key - Qt::Key_1]);
        return true;
    }
    if (mods == Qt::NoModifier && !typing()) {
        switch (key) {
        case Qt::Key_Left: case Qt::Key_Right: case Qt::Key_Up: case Qt::Key_Down: case Qt::Key_PageUp: case Qt::Key_PageDown:
            if (!e->isAutoRepeat()) emit jogKey(key);
            return false;  // other views keep their own use of these keys
        default: break;
        }
    }
    return false;
}
