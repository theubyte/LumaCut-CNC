#pragma once
#include <QCoreApplication>
#include <QJSEngine>
#include <QQmlEngine>

// One object for C++ and QML: T::instance() anywhere, "T" as a QML singleton. Lives as long as the app.
// T must have no default constructor (take a parent), or QML would quietly build its own second object.
#define LC_SINGLETON(T)                                                                     \
public:                                                                                     \
    static T* instance() { static T* s = new T(QCoreApplication::instance()); return s; }   \
    static T* create(QQmlEngine*, QJSEngine*) {                                             \
        T* s = instance();                                                                  \
        QJSEngine::setObjectOwnership(s, QJSEngine::CppOwnership);                          \
        return s;                                                                           \
    }
