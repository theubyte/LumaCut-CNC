#pragma once
#include <QAbstractNativeEventFilter>
#include <QObject>
#include <QPointer>
#include <QQuickItem>
#include <QQuickWindow>
#include <QtQml/qqmlregistration.h>

/**
 * Makes the frameless window a real Windows 11 window: shadow, rounded corners, resize borders, drag with snap,
 * double click on the bar, and snap layouts on the maximize button.
 * Parts of the title bar with a MouseArea stay clickable; everything else in it drags the window.
 * Real mouse input on the maximize button arrives here as non-client messages; the test driver's clicks reach its MouseArea.
 */
class WindowChrome : public QObject, public QAbstractNativeEventFilter {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QQuickWindow* window READ window WRITE setWindow NOTIFY changed)
    Q_PROPERTY(QQuickItem* titleBar MEMBER m_titleBar NOTIFY changed)
    Q_PROPERTY(QQuickItem* maxButton MEMBER m_maxButton NOTIFY changed)
    Q_PROPERTY(bool dark READ dark WRITE setDark NOTIFY changed)
    Q_PROPERTY(bool maxHovered READ maxHovered NOTIFY stateChanged)
    Q_PROPERTY(bool maxPressed READ maxPressed NOTIFY stateChanged)
    Q_PROPERTY(bool maximized READ maximized NOTIFY stateChanged)
    /** Windows lets a maximized window hang over the screen edge by the frame width: content stays this far in. */
    Q_PROPERTY(int inset READ inset NOTIFY stateChanged)
public:
    explicit WindowChrome(QObject* parent = nullptr);
    ~WindowChrome() override;
    QQuickWindow* window() const { return m_window; }
    void setWindow(QQuickWindow* w);
    bool dark() const { return m_dark; }
    void setDark(bool v);
    bool maxHovered() const { return m_maxHovered; }
    bool maxPressed() const { return m_maxPressed; }
    bool maximized() const;
    int inset() const { return m_inset; }
    Q_INVOKABLE void toggleMaximize();
    bool nativeEventFilter(const QByteArray& type, void* message, qintptr* result) override;
signals:
    void changed();
    void stateChanged();
private:
    void applyNative();
    int hitTest(int physicalX, int physicalY) const;
    void setMaxState(bool hovered, bool pressed);
    void updateInset();
    QPointer<QQuickWindow> m_window;
    QQuickItem* m_titleBar = nullptr;
    QQuickItem* m_maxButton = nullptr;
    quintptr m_hwnd = 0;
    bool m_dark = false;
    bool m_maxHovered = false;
    bool m_maxPressed = false;
    int m_inset = 0;
};
