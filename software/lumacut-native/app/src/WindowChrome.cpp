#include "WindowChrome.h"
#include <QCoreApplication>
#include <QGuiApplication>
#include <QtMath>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "user32.lib")
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
#endif
#ifndef DWMWA_WINDOW_CORNER_PREFERENCE
#define DWMWA_WINDOW_CORNER_PREFERENCE 33
#endif
#endif

WindowChrome::WindowChrome(QObject* parent) : QObject(parent) {
    QCoreApplication::instance()->installNativeEventFilter(this);
}
WindowChrome::~WindowChrome() {
    if (auto* app = QCoreApplication::instance()) app->removeNativeEventFilter(this);
}
void WindowChrome::setWindow(QQuickWindow* w) {
    if (w == m_window) return;
    m_window = w;
    if (w) {
        connect(w, &QWindow::visibilityChanged, this, [this] { updateInset(); emit stateChanged(); });
        connect(w, &QWindow::widthChanged, this, &WindowChrome::updateInset);
        connect(w, &QWindow::heightChanged, this, &WindowChrome::updateInset);
        applyNative();
    }
    emit changed();
}
void WindowChrome::setDark(bool v) {
    if (v == m_dark) return;
    m_dark = v;
#ifdef Q_OS_WIN
    if (m_hwnd) {
        BOOL on = v;
        DwmSetWindowAttribute(HWND(m_hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE, &on, sizeof on);
    }
#endif
    emit changed();
}
bool WindowChrome::maximized() const { return m_window && m_window->visibility() == QWindow::Maximized; }
void WindowChrome::toggleMaximize() {
    if (!m_window) return;
    if (maximized()) m_window->showNormal();
    else m_window->showMaximized();
}
void WindowChrome::setMaxState(bool hovered, bool pressed) {
    if (hovered == m_maxHovered && pressed == m_maxPressed) return;
    m_maxHovered = hovered;
    m_maxPressed = pressed;
    emit stateChanged();
}

void WindowChrome::updateInset() {
    int v = 0;
#ifdef Q_OS_WIN
    if (m_hwnd && IsZoomed(HWND(m_hwnd))) {
        RECT r;
        MONITORINFO mi{sizeof mi};
        if (GetWindowRect(HWND(m_hwnd), &r) && GetMonitorInfoW(MonitorFromWindow(HWND(m_hwnd), MONITOR_DEFAULTTONEAREST), &mi))
            v = qCeil(qMax<LONG>(0, mi.rcWork.left - r.left) / m_window->effectiveDevicePixelRatio());
    }
#endif
    if (v != m_inset) { m_inset = v; emit stateChanged(); }
}

void WindowChrome::applyNative() {
#ifdef Q_OS_WIN
    HWND hwnd = HWND(m_window->winId());  // creates the native window; it stays hidden until main.cpp shows it
    m_hwnd = quintptr(hwnd);              // from here on the filter handles this window
    LONG_PTR style = GetWindowLongPtrW(hwnd, GWL_STYLE);
    style &= ~LONG_PTR(WS_POPUP);
    style |= WS_OVERLAPPED | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX;
    SetWindowLongPtrW(hwnd, GWL_STYLE, style);
    const MARGINS shadow{0, 0, 1, 0};   // one row of the frame stays, so DWM keeps the shadow
    DwmExtendFrameIntoClientArea(hwnd, &shadow);
    const DWORD round = 2;              // DWMWCP_ROUND
    DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, &round, sizeof round);
    BOOL on = m_dark;
    DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &on, sizeof on);
    SetWindowPos(hwnd, nullptr, 0, 0, 0, 0, SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
#endif
}

#ifdef Q_OS_WIN
// A pointer-handling child under the point keeps the click for itself; the rest of the bar is caption.
static bool interactiveAt(QQuickItem* item, const QPointF& scene) {
    const auto children = item->childItems();
    for (auto it = children.crbegin(); it != children.crend(); ++it) {
        QQuickItem* c = *it;
        if (!c->isVisible() || !c->isEnabled()) continue;
        if (!c->contains(c->mapFromScene(scene))) { if (interactiveAt(c, scene)) return true; continue; }
        if (c->acceptedMouseButtons() != Qt::NoButton) return true;
        if (interactiveAt(c, scene)) return true;
    }
    return false;
}
int WindowChrome::hitTest(int physicalX, int physicalY) const {
    HWND hwnd = HWND(m_hwnd);
    POINT pt{physicalX, physicalY};
    ScreenToClient(hwnd, &pt);
    RECT rc;
    GetClientRect(hwnd, &rc);
    const bool isMax = IsZoomed(hwnd);
    if (!isMax) {
        const int b = GetSystemMetricsForDpi(SM_CXSIZEFRAME, GetDpiForWindow(hwnd)) + GetSystemMetricsForDpi(SM_CXPADDEDBORDER, GetDpiForWindow(hwnd));
        const bool l = pt.x < b, r = pt.x >= rc.right - b, t = pt.y < b / 2 + 1, bo = pt.y >= rc.bottom - b;
        if (t && l) return HTTOPLEFT;
        if (t && r) return HTTOPRIGHT;
        if (bo && l) return HTBOTTOMLEFT;
        if (bo && r) return HTBOTTOMRIGHT;
        if (t) return HTTOP;
        if (l) return HTLEFT;
        if (r) return HTRIGHT;
        if (bo) return HTBOTTOM;
    }
    if (!m_titleBar) return HTCLIENT;
    const qreal dpr = m_window->effectiveDevicePixelRatio();
    const QPointF scene(pt.x / dpr, pt.y / dpr);
    if (!m_titleBar->contains(m_titleBar->mapFromScene(scene))) return HTCLIENT;
    if (m_maxButton && m_maxButton->isVisible() && m_maxButton->contains(m_maxButton->mapFromScene(scene))) return HTMAXBUTTON;
    return interactiveAt(m_titleBar, scene) ? HTCLIENT : HTCAPTION;
}
#endif

bool WindowChrome::nativeEventFilter(const QByteArray& type, void* message, qintptr* result) {
#ifdef Q_OS_WIN
    if (type != "windows_generic_MSG" || !m_window || !m_hwnd) return false;
    MSG* msg = static_cast<MSG*>(message);
    if (quintptr(msg->hwnd) != m_hwnd) return false;
    switch (msg->message) {
    case WM_NCCALCSIZE:
        // The client area is the whole window, title bar and frame included.
        if (msg->wParam) { *result = 0; return true; }
        return false;
    case WM_GETMINMAXINFO: {
        // The size when maximized stays Windows' own; Main.qml keeps the content inside (inset).
        auto* info = reinterpret_cast<MINMAXINFO*>(msg->lParam);
        const qreal dpr = m_window->effectiveDevicePixelRatio();
        info->ptMinTrackSize = {LONG(m_window->minimumWidth() * dpr), LONG(m_window->minimumHeight() * dpr)};
        info->ptMaxTrackSize = {16384, 16384};
        *result = 0;
        return true;
    }
    case WM_NCHITTEST:
        *result = hitTest(GET_X_LPARAM(msg->lParam), GET_Y_LPARAM(msg->lParam));
        return true;
    case WM_NCMOUSEMOVE:
        if (msg->wParam == HTMAXBUTTON) {
            TRACKMOUSEEVENT t{sizeof t, TME_LEAVE | TME_NONCLIENT, msg->hwnd, 0};
            TrackMouseEvent(&t);
            setMaxState(true, m_maxPressed);
            *result = 0;
            return false;    // Windows still needs it for the snap layout flyout
        }
        setMaxState(false, false);
        return false;
    case WM_MOUSEMOVE:
    case WM_NCMOUSELEAVE:
        setMaxState(false, false);
        return false;
    case WM_NCLBUTTONDOWN:
        if (msg->wParam == HTMAXBUTTON) { setMaxState(true, true); *result = 0; return true; }
        return false;
    case WM_NCLBUTTONUP:
        if (msg->wParam == HTMAXBUTTON) {
            const bool was = m_maxPressed;
            setMaxState(true, false);
            if (was) toggleMaximize();
            *result = 0;
            return true;
        }
        return false;
    default:
        return false;
    }
#else
    Q_UNUSED(type) Q_UNUSED(message) Q_UNUSED(result)
    return false;
#endif
}
