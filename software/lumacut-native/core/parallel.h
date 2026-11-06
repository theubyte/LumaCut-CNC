#pragma once
/**
 * Mehrkernige Schleifen über den globalen QThreadPool. Der Aufrufer arbeitet mit und wartet nur auf Helfer, die
 * schon laufen; nichts steht je in der Warteschlange. Darum sind Aufrufe auch geschachtelt und im Pool sicher,
 * anders als QtConcurrent::blockingMap, das in Pool-Threads sich gegenseitig blockieren kann.
 * Ausnahmen aus fn kommen beim Aufrufer an (die erste).
 */
#include <algorithm>
#include <cstddef>
#include <functional>

namespace lumacut {

/** fn(i) für jedes i aus [0, n), frei verteilt. */
void parallelFor(std::ptrdiff_t n, const std::function<void(std::ptrdiff_t)>& fn);

int idealThreads();

/** fn(begin, end) für Blöcke von [0, n). Kleine Mengen laufen direkt. */
template <class Fn>
void parallelBlocks(std::ptrdiff_t n, std::ptrdiff_t minBlock, Fn&& fn) {
    if (n <= 0) return;
    const std::ptrdiff_t threads = idealThreads();
    const std::ptrdiff_t block = std::max(minBlock, n / (threads * 4) + 1);
    if (threads == 1 || n <= block) { fn(std::ptrdiff_t(0), n); return; }
    const std::ptrdiff_t count = (n + block - 1) / block;
    parallelFor(count, [&](std::ptrdiff_t b) { fn(b * block, std::min(n, (b + 1) * block)); });
}

}  // namespace lumacut
