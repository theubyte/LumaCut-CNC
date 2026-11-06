#include "Automation.h"
#include <QCoreApplication>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMetaObject>
#include <QQuickItem>
#include <QQuickWindow>
#include <QSGRendererInterface>
#include <QTcpServer>
#include <QTcpSocket>
#include <QtGui/QKeyEvent>
#include <QtGui/QMouseEvent>
#include <QtGui/QWheelEvent>
#ifdef Q_OS_WIN
#include <windows.h>
#include <psapi.h>
#pragma comment(lib, "psapi.lib")
#endif

static QQuickItem* findIn(QQuickItem* item, const QString& name) {
    if (item->objectName() == name && item->isVisible()) return item;
    const auto children = item->childItems();
    for (QQuickItem* c : children) if (auto* hit = findIn(c, name)) return hit;
    return nullptr;
}
static void treeOf(QQuickItem* item, QJsonArray& out) {
    if (!item->isVisible()) return;
    if (!item->objectName().isEmpty()) {
        const QRectF r = item->mapRectToScene(QRectF(0, 0, item->width(), item->height()));
        out.append(QJsonObject{{"name", item->objectName()}, {"type", QString::fromLatin1(item->metaObject()->className())},
                               {"x", r.x()}, {"y", r.y()}, {"w", r.width()}, {"h", r.height()}});
    }
    const auto children = item->childItems();
    for (QQuickItem* c : children) treeOf(c, out);
}

Automation::Automation(QQuickWindow* window, quint16 port, const QElapsedTimer& started, QObject* parent)
    : QObject(parent), m_window(window), m_server(new QTcpServer(this)), m_started(started) {
    connect(window, &QQuickWindow::frameSwapped, this, [this] {
        if (m_firstFrameMs < 0) m_firstFrameMs = m_started.elapsed();
        ++m_frames;
    }, Qt::QueuedConnection);
    m_fpsTimer.start();
    m_server->listen(QHostAddress::LocalHost, port);
    connect(m_server, &QTcpServer::newConnection, this, [this] {
        while (auto* s = m_server->nextPendingConnection()) {
            connect(s, &QTcpSocket::disconnected, s, &QObject::deleteLater);
            connect(s, &QTcpSocket::readyRead, this, [this, s] {
                while (s->canReadLine()) {
                    const QJsonObject cmd = QJsonDocument::fromJson(s->readLine()).object();
                    QJsonObject reply;
                    if (cmd.isEmpty()) reply = {{"error", "bad json"}};
                    else reply = handle(cmd);
                    s->write(QJsonDocument(reply).toJson(QJsonDocument::Compact) + '\n');
                    s->flush();
                }
            });
        }
    });
}

QQuickItem* Automation::findItem(const QString& name) const { return m_window ? findIn(m_window->contentItem(), name) : nullptr; }

void Automation::sendMouse(QPointF pos, int type, Qt::MouseButton button, Qt::MouseButtons buttons, Qt::KeyboardModifiers mods) {
    QMouseEvent ev(QEvent::Type(type), pos, pos, m_window->mapToGlobal(pos), button, buttons, mods);
    QCoreApplication::sendEvent(m_window, &ev);
}

QJsonObject Automation::handle(const QJsonObject& c) {
    const QString cmd = c["cmd"].toString();
    if (!m_window) return {{"error", "no window"}};
    if (cmd == "tree") {
        QJsonArray out;
        treeOf(m_window->contentItem(), out);
        return {{"items", out}};
    }
    if (cmd == "find" || cmd == "get" || cmd == "click" || cmd == "invoke") {
        auto* item = findItem(c["name"].toString());
        if (!item) return {{"error", "not found: " + c["name"].toString()}};
        const QRectF r = item->mapRectToScene(QRectF(0, 0, item->width(), item->height()));
        if (cmd == "find") return {{"x", r.x()}, {"y", r.y()}, {"w", r.width()}, {"h", r.height()}, {"enabled", item->isEnabled()}, {"type", QString::fromLatin1(item->metaObject()->className())}};
        if (cmd == "get") return {{"value", QJsonValue::fromVariant(item->property(c["prop"].toString().toUtf8()))}};
        if (cmd == "invoke") {
            QVariant ret;
            const QJsonArray a = c["args"].toArray();
            QVariant v0 = a.size() > 0 ? a[0].toVariant() : QVariant();
            bool ok;
            if (a.isEmpty()) ok = QMetaObject::invokeMethod(item, c["method"].toString().toUtf8(), Qt::DirectConnection, Q_RETURN_ARG(QVariant, ret));
            else ok = QMetaObject::invokeMethod(item, c["method"].toString().toUtf8(), Qt::DirectConnection, Q_RETURN_ARG(QVariant, ret), Q_ARG(QVariant, v0));
            return ok ? QJsonObject{{"value", QJsonValue::fromVariant(ret)}} : QJsonObject{{"error", "invoke failed"}};
        }
        const QPointF p = r.center();
        sendMouse(p, QEvent::MouseMove, Qt::NoButton, Qt::NoButton);
        sendMouse(p, QEvent::MouseButtonPress, Qt::LeftButton, Qt::LeftButton);
        sendMouse(p, QEvent::MouseButtonRelease, Qt::LeftButton, Qt::NoButton);
        return {{"ok", true}};
    }
    if (cmd == "mouse") {
        const QPointF p(c["x"].toDouble(), c["y"].toDouble());
        const QString t = c["type"].toString();
        const auto mods = Qt::KeyboardModifiers(c["mods"].toInt());
        if (t == "move") sendMouse(p, QEvent::MouseMove, Qt::NoButton, c["down"].toBool() ? Qt::LeftButton : Qt::NoButton, mods);
        else if (t == "press") sendMouse(p, QEvent::MouseButtonPress, Qt::LeftButton, Qt::LeftButton, mods);
        else if (t == "release") sendMouse(p, QEvent::MouseButtonRelease, Qt::LeftButton, Qt::NoButton, mods);
        else if (t == "rpress") sendMouse(p, QEvent::MouseButtonPress, Qt::RightButton, Qt::RightButton, mods);
        else if (t == "rrelease") sendMouse(p, QEvent::MouseButtonRelease, Qt::RightButton, Qt::NoButton, mods);
        return {{"ok", true}};
    }
    if (cmd == "wheel") {
        const QPointF p(c["x"].toDouble(), c["y"].toDouble());
        QWheelEvent ev(p, m_window->mapToGlobal(p), QPoint(), QPoint(0, c["dy"].toInt(120)), Qt::NoButton, Qt::KeyboardModifiers(c["mods"].toInt()), Qt::NoScrollPhase, false);
        QCoreApplication::sendEvent(m_window, &ev);
        return {{"ok", true}};
    }
    if (cmd == "key") {
        const int key = c["key"].toInt();
        const auto mods = Qt::KeyboardModifiers(c["mods"].toInt());
        QKeyEvent press(QEvent::KeyPress, key, mods, c["text"].toString()), rel(QEvent::KeyRelease, key, mods);
        QCoreApplication::sendEvent(m_window, &press);
        QCoreApplication::sendEvent(m_window, &rel);
        return {{"ok", true}};
    }
    if (cmd == "text") {
        const QString text = c["text"].toString();
        for (QChar ch : text) {
            QKeyEvent press(QEvent::KeyPress, 0, Qt::NoModifier, QString(ch)), rel(QEvent::KeyRelease, 0, Qt::NoModifier, QString(ch));
            QCoreApplication::sendEvent(m_window, &press);
            QCoreApplication::sendEvent(m_window, &rel);
        }
        return {{"ok", true}};
    }
    if (cmd == "shot") {
        const QImage img = m_window->grabWindow();
        return img.save(c["path"].toString()) ? QJsonObject{{"ok", true}, {"w", img.width()}, {"h", img.height()}} : QJsonObject{{"error", "save failed"}};
    }
    if (cmd == "stats") {
        QJsonObject r;
        const qint64 now = m_fpsTimer.elapsed();
        if (now > m_markTime) m_lastFps = double(m_frames - m_markFrames) * 1000.0 / double(now - m_markTime);
        m_markTime = now; m_markFrames = m_frames;
        r["fps"] = m_lastFps;
        r["frames"] = double(m_frames);
        r["firstFrameMs"] = double(m_firstFrameMs);
        auto* ri = m_window->rendererInterface();
        r["api"] = int(ri->graphicsApi());
        r["device"] = m_window->property("gpuName").toString();
#ifdef Q_OS_WIN
        PROCESS_MEMORY_COUNTERS pmc{};
        if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof pmc)) r["memMb"] = double(pmc.WorkingSetSize) / (1024.0 * 1024.0);
#endif
        return r;
    }
    if (cmd == "quit") { QCoreApplication::quit(); return {{"ok", true}}; }
    return {{"error", "unknown command " + cmd}};
}
