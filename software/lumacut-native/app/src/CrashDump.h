#pragma once
#include <QtGlobal>

/** Writes a minidump to %LOCALAPPDATA%\LumaCut\crashes when the app crashes. Call once, first thing in main. */
void installCrashDump();
