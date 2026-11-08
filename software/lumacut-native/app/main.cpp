#include <QGuiApplication>
#include <QLoggingCategory>
#include <QQmlApplicationEngine>
#include "PaperThumbs.h"
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSurfaceFormat>
#include <QElapsedTimer>
#include "src/Automation.h"
#include "src/CrashDump.h"
namespace lumacut { const char* version(); }

int main(int argc, char* argv[]) {
    installCrashDump();
    QElapsedTimer started;
    started.start();
    // Direct3D 11 through QRhi: broad driver support and compute shaders. LUMACUT_RHI overrides for tests (d3d12).
    const QByteArray rhiEnv = qgetenv("LUMACUT_RHI");
    QQuickWindow::setGraphicsApi(rhiEnv == "d3d12" ? QSGRendererInterface::Direct3D12 : QSGRendererInterface::Direct3D11);
    if (qEnvironmentVariableIsSet("LUMACUT_BENCH")) {       // benchmarks run without vsync to measure real frame cost
        QSurfaceFormat fmt = QSurfaceFormat::defaultFormat();
        fmt.setSwapInterval(0);
        QSurfaceFormat::setDefaultFormat(fmt);
    }
    QGuiApplication::setApplicationName("LumaCut Studio");
    QGuiApplication::setOrganizationName("LumaCut");
    QGuiApplication::setApplicationVersion(QString::fromLatin1(lumacut::version()));
    QGuiApplication app(argc, argv);
    QQuickStyle::setStyle("Basic");

    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.addImageProvider(QStringLiteral("papier"), new PaperThumbs);
    engine.loadFromModule("LumaCut", "Main");
    if (engine.rootObjects().isEmpty()) return 1;
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());

    // Test driver for the real window: only with LUMACUT_AUTOMATION_PORT set, only on localhost.
    bool ok = false;
    const int port = qEnvironmentVariableIntValue("LUMACUT_AUTOMATION_PORT", &ok);
    Automation* automation = nullptr;
    if (ok && port > 0 && window) automation = new Automation(window, quint16(port), started, &app);
    Q_UNUSED(automation);
    // Shown only now, so the automation sees the very first frame.
    if (window) window->showMaximized();
    return app.exec();
}
