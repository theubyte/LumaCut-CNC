#pragma once
#include <QObject>
#include <QPointer>
#include <QQuickItem>
#include <QQuickWindow>
#include <QtQml/qqmlregistration.h>
#include "Singleton.h"

/**
 * Glue of the window: where overlays live, which view is open, and the keys that work everywhere.
 * Key events are filtered on the window itself, so they hold for real input and the test driver alike.
 *   Shell.navigate("maschine")  Shell.dest  Shell.overlay  Shell.modalOpen  Shell.projectTitle  Shell.projectDirty
 *   signals: estopKey, jogKey(int key) (arrows, page up/down, no repeat, not while typing or in a dialog)
 */
class Shell : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Shell)
    Q_PROPERTY(QQuickItem* overlay READ overlay WRITE setOverlay NOTIFY overlayChanged)
    Q_PROPERTY(bool modalOpen READ modalOpen NOTIFY modalChanged)
    Q_PROPERTY(QString dest READ dest NOTIFY destChanged)
    Q_PROPERTY(QString projectTitle READ projectTitle WRITE setProjectTitle NOTIFY projectChanged)
    Q_PROPERTY(bool projectDirty READ projectDirty WRITE setProjectDirty NOTIFY projectChanged)
public:
    explicit Shell(QObject* parent);
    QQuickItem* overlay() const { return m_overlay; }
    void setOverlay(QQuickItem* v) { if (v != m_overlay) { m_overlay = v; emit overlayChanged(); } }
    bool modalOpen() const { return !m_modals.isEmpty(); }
    QString dest() const { return m_dest; }
    Q_INVOKABLE void navigate(const QString& key);
    QString projectTitle() const { return m_title; }
    void setProjectTitle(const QString& v) { if (v != m_title) { m_title = v; emit projectChanged(); } }
    bool projectDirty() const { return m_dirty; }
    void setProjectDirty(bool v) { if (v != m_dirty) { m_dirty = v; emit projectChanged(); } }
    /** The dialog or menu on top gets Esc (method requestClose()) and keeps Tab inside itself. */
    Q_INVOKABLE void pushModal(QQuickItem* item);
    Q_INVOKABLE void popModal(QQuickItem* item);
    Q_INVOKABLE void attachWindow(QQuickWindow* window);
    /** True while a text field has the keyboard. */
    Q_INVOKABLE bool typing() const;
protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
signals:
    void overlayChanged();
    void modalChanged();
    void destChanged();
    void projectChanged();
    void estopKey();
    void jogKey(int key);
    /** Alt+S: the go dialog's only keyboard way to start. */
    void goKey();
private:
    void cycleFocus(bool back);
    QPointer<QQuickItem> m_overlay;
    QList<QPointer<QQuickItem>> m_modals;
    QPointer<QQuickWindow> m_window;
    QString m_dest;
    QString m_title = QStringLiteral("Neues Projekt");
    bool m_dirty = false;
};
