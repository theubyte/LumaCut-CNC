#pragma once
#include <QElapsedTimer>
#include <QHash>
#include <QJsonObject>
#include <QObject>
#include <QPointer>
#include <QPointF>

class QQuickItem;
class QQuickWindow;
class QTcpServer;
class QTcpSocket;

/**
 * Drives and inspects the REAL window for tests (see tests/ui/driver.py). JSON lines over TCP on 127.0.0.1.
 * Exists only when LUMACUT_AUTOMATION_PORT is set. Input goes through normal window events, so it behaves
 * like a user; it has no way around the go dialog.
 *
 * Commands: find{name} get{name,prop} click{name} mouse{x,y,type,buttons?} wheel{x,y,dy} key{key,mods?} text{text}
 *           invoke{name,method,args?} shot{path} stats{} tree{} quit{}
 */
class Automation : public QObject {
    Q_OBJECT
public:
    Automation(QQuickWindow* window, quint16 port, const QElapsedTimer& started, QObject* parent);

private:
    QJsonObject handle(const QJsonObject& cmd);
    QQuickItem* findItem(const QString& name) const;
    void sendMouse(QPointF pos, int type, Qt::MouseButton button, Qt::MouseButtons buttons, Qt::KeyboardModifiers mods = {});

    QPointer<QQuickWindow> m_window;
    QTcpServer* m_server;
    QElapsedTimer m_started;
    qint64 m_firstFrameMs = -1;
    QElapsedTimer m_fpsTimer;
    quint64 m_frames = 0, m_markFrames = 0;
    double m_lastFps = 0;
    qint64 m_markTime = 0;
};
