#include "core/parallel.h"

#include <QThread>
#include <QThreadPool>
#include <atomic>
#include <condition_variable>
#include <exception>
#include <mutex>

namespace lumacut {

int idealThreads() { return std::max(1, QThread::idealThreadCount()); }

void parallelFor(std::ptrdiff_t n, const std::function<void(std::ptrdiff_t)>& fn) {
    if (n <= 0) return;
    if (n == 1) { fn(0); return; }
    struct State {
        std::atomic<std::ptrdiff_t> next{0};
        std::mutex mutex;
        std::condition_variable idle;
        int helpers = 0;
        std::exception_ptr error;
    } st;
    const auto loop = [&] {
        for (;;) {
            const std::ptrdiff_t i = st.next.fetch_add(1, std::memory_order_relaxed);
            if (i >= n) return;
            try {
                fn(i);
            } catch (...) {
                std::lock_guard lock(st.mutex);
                if (!st.error) st.error = std::current_exception();
                st.next.store(n, std::memory_order_relaxed);
            }
        }
    };
    QThreadPool* pool = QThreadPool::globalInstance();
    const std::ptrdiff_t wanted = std::min<std::ptrdiff_t>(n - 1, idealThreads() - 1);
    for (std::ptrdiff_t h = 0; h < wanted; ++h) {
        { std::lock_guard lock(st.mutex); ++st.helpers; }
        const bool started = pool->tryStart([&] {
            loop();
            std::lock_guard lock(st.mutex);
            if (--st.helpers == 0) st.idle.notify_all();
        });
        if (!started) {
            std::lock_guard lock(st.mutex);
            --st.helpers;
            break;  // Pool ist voll: den Rest macht, wer schon läuft
        }
    }
    loop();
    std::unique_lock lock(st.mutex);
    st.idle.wait(lock, [&] { return st.helpers == 0; });
    if (st.error) std::rethrow_exception(st.error);
}

}  // namespace lumacut
