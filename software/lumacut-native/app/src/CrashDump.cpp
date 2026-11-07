#include "CrashDump.h"
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#include <dbghelp.h>
#include <cwchar>
#pragma comment(lib, "dbghelp.lib")

// A crash leaves a small minidump in %LOCALAPPDATA%\LumaCut\crashes. With the matching .pdb from dist\
// (tools/msi.cmd keeps it next to the MSI) the place of the crash can be read later.
static wchar_t g_dir[MAX_PATH];

static LONG WINAPI writeDump(EXCEPTION_POINTERS* info) {
    SYSTEMTIME t;
    GetLocalTime(&t);
    wchar_t path[MAX_PATH];
    swprintf(path, MAX_PATH, L"%ls\\LumaCutStudio-%04u%02u%02u-%02u%02u%02u-%lu.dmp", g_dir, t.wYear, t.wMonth, t.wDay, t.wHour,
             t.wMinute, t.wSecond, GetCurrentProcessId());
    HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file != INVALID_HANDLE_VALUE) {
        MINIDUMP_EXCEPTION_INFORMATION ex{GetCurrentThreadId(), info, FALSE};
        MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(), file,
                          MINIDUMP_TYPE(MiniDumpWithIndirectlyReferencedMemory | MiniDumpWithThreadInfo), &ex, nullptr, nullptr);
        CloseHandle(file);
    }
    return EXCEPTION_CONTINUE_SEARCH;   // Windows still records the crash as before
}

void installCrashDump() {
    DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", g_dir, MAX_PATH);
    if (n == 0 || n > MAX_PATH - 40) return;
    wcscat_s(g_dir, L"\\LumaCut");
    CreateDirectoryW(g_dir, nullptr);
    wcscat_s(g_dir, L"\\crashes");
    CreateDirectoryW(g_dir, nullptr);
    SetUnhandledExceptionFilter(writeDump);
}
#else
void installCrashDump() {}
#endif
