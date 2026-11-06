#include "Toast.h"
#include <QTimer>

void Toast::show(const QString& text, const QString& tone) {
    const int id = ++m_next;
    while (m_items.size() > 3) m_items.removeFirst();
    m_items.append(QVariantMap{{"id", id}, {"text", text}, {"tone", tone}});
    m_last = text;
    emit itemsChanged();
    QTimer::singleShot(tone == QLatin1String("bad") ? 8000 : 3500, this, [this, id] { dismiss(id); });
}
void Toast::dismiss(int id) {
    for (int i = 0; i < m_items.size(); ++i)
        if (m_items[i].toMap().value("id").toInt() == id) { m_items.removeAt(i); emit itemsChanged(); return; }
}

void Confirm::askNative(const QVariantMap& request, std::function<void(bool)> callback) {
    if (m_cb) { auto old = std::move(m_cb); m_cb = nullptr; old(false); }  // never two questions at once
    m_req = request;
    m_cb = std::move(callback);
    emit changed();
}
void Confirm::ask(const QVariantMap& request, const QJSValue& callback) {
    askNative(request, [callback](bool yes) mutable { if (callback.isCallable()) callback.call({yes}); });
}
void Confirm::answer(bool yes) {
    if (!m_cb) return;
    auto cb = std::move(m_cb);
    m_cb = nullptr;
    emit changed();
    cb(yes);
}
