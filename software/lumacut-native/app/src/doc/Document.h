#pragma once
#include <QHash>
#include <QObject>
#include <QStringList>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include <memory>
#include <vector>
#include "Singleton.h"
#include "core/model.h"

/**
 * The open project, undo history, selection. Everything that edits the design goes through here: editor, importers,
 * generators, PCB, workshop. C++: Document::instance(); QML: Document.
 *
 * One commit = one undo step. While dragging: checkpoint() once, then mutate() as often as needed.
 *
 *   doc->addElements(std::move(els));                      // onto the active plate, selects them, one step
 *   doc->commit([](Document::State& s) { s.title = "x"; });
 *   doc->updateElements(ids, [](lumacut::Element& e) { e.transform.x += 1; });
 *   const lumacut::Document& m = doc->doc();               // the whole model, built on demand
 *
 * Structural sharing: elements are immutable and shared between undo steps, a step holds only pointers. Only what
 * changed is copied, so a step costs microseconds for few elements and about 1 ms per 100,000 for the list itself.
 * Never change an element behind a pointer; go through updateElements() or State::editElements().
 */
class Document : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Document)
    Q_PROPERTY(QString title READ title WRITE setTitle NOTIFY titleChanged)
    Q_PROPERTY(bool dirty READ dirty NOTIFY dirtyChanged)
    Q_PROPERTY(QString filePath READ filePath NOTIFY filePathChanged)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY historyChanged)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY historyChanged)
    Q_PROPERTY(QStringList selection READ selection WRITE select NOTIFY selectionChanged)
    Q_PROPERTY(int selectionCount READ selectionCount NOTIFY selectionChanged)
    Q_PROPERTY(QString activeLayer READ activeLayer WRITE setActiveLayer NOTIFY activeLayerChanged)
    Q_PROPERTY(int elementCount READ elementCount NOTIFY changed)
    Q_PROPERTY(int plateCount READ plateCount NOTIFY changed)
    Q_PROPERTY(int activePlate READ activePlate WRITE setActivePlate NOTIFY changed)
    Q_PROPERTY(bool empty READ empty NOTIFY changed)
    Q_PROPERTY(quint64 revision READ revision NOTIFY changed)
public:
    using ElementPtr = std::shared_ptr<const lumacut::Element>;
    using ElementList = std::vector<ElementPtr>;

    /** One version of the project. Copying is a few pointers. */
    struct State {
        QString title;
        std::shared_ptr<std::vector<lumacut::Layer>> layerList;
        std::shared_ptr<ElementList> elementList;
        int plateCount = 1;
        int activePlate = 0;
        QJsonObject extra;

        const std::vector<lumacut::Layer>& layers() const { return *layerList; }
        const ElementList& elements() const { return *elementList; }
        /** Own copies of the lists on first use; afterwards cheap. */
        std::vector<lumacut::Layer>& editLayers();
        ElementList& editElements();
    };

    explicit Document(QObject* parent);

    const State& state() const { return m_state; }
    const ElementList& elements() const { return *m_state.elementList; }
    const std::vector<lumacut::Layer>& layers() const { return *m_state.layerList; }
    const lumacut::Layer* layer(const QString& id) const;
    /** By id, nullptr if unknown. Pointer stays valid as long as you hold it through elementPtr(). */
    const lumacut::Element* element(const QString& id) const;
    ElementPtr elementPtr(const QString& id) const;
    int indexOf(const QString& id) const;

    /**
     * The project as plain model. Built on first use after a change, then cached, so a reference is valid until the next
     * change. On workers use snapshot() and build there; building takes tens of ms at 100,000 elements.
     */
    const lumacut::Document& doc() const;
    /** Thread-safe to hand to a worker: captures the current state, builds nothing yet. */
    struct Snapshot {
        State state;
        lumacut::Document build() const;
    };
    Snapshot snapshot() const { return {m_state}; }
    QByteArray toJson() const { return doc().toJson(); }
    /** For tests and small tools. */
    Q_INVOKABLE QString jsonText() const { return QString::fromUtf8(toJson()); }

    /** Replace the state as one undo step. */
    void commit(const std::function<void(State&)>& fn);
    /** Change without a new undo step (while dragging). Call checkpoint() once before. */
    void mutate(const std::function<void(State&)>& fn);
    Q_INVOKABLE void checkpoint();
    /** Change these elements as one undo step, copying only them. Large sets run on all cores; fn must be thread-safe. */
    void updateElements(const QStringList& ids, const std::function<void(lumacut::Element&)>& fn);
    void mutateElements(const QStringList& ids, const std::function<void(lumacut::Element&)>& fn);

    /** Onto the active plate; selects them. One undo step. Elements with an unknown layer go to the active layer. */
    void addElements(std::vector<lumacut::Element> elements);
    /** Layer by internal name ("Gravieren", "Linie", "Schneiden"); a missing standard layer is created. */
    QString layerByName(const QString& name);

    /** Replaces the project, clears the history. */
    void load(lumacut::Document doc, const QString& filePath = {});
    /** Parses JSON; on failure the project stays and `error` says why. */
    bool loadJson(QByteArrayView json, const QString& filePath = {}, QString* error = nullptr);
    Q_INVOKABLE void reset();
    /** Saved: not dirty any more, optional new path. */
    void markSaved(const QString& filePath = {});

    QString title() const { return m_state.title; }
    void setTitle(const QString& v);
    bool dirty() const { return m_dirty; }
    QString filePath() const { return m_filePath; }
    bool canUndo() const { return !m_past.empty(); }
    bool canRedo() const { return !m_future.empty(); }
    int undoDepth() const { return int(m_past.size()); }
    QStringList selection() const { return m_selection; }
    int selectionCount() const { return int(m_selection.size()); }
    bool isSelected(const QString& id) const { return m_selectionSet.contains(id); }
    const QSet<QString>& selectionSet() const { return m_selectionSet; }
    QString activeLayer() const { return m_activeLayer; }
    void setActiveLayer(const QString& id);
    int elementCount() const { return int(elements().size()); }
    int plateCount() const { return m_state.plateCount; }
    int activePlate() const { return m_state.activePlate; }
    void setActivePlate(int i);
    bool empty() const { return elements().empty(); }
    quint64 revision() const { return m_revision; }

    Q_INVOKABLE void undo();
    Q_INVOKABLE void redo();
    Q_INVOKABLE void select(const QStringList& ids);
    Q_INVOKABLE void clearSelection() { select({}); }
    Q_INVOKABLE void addPlate();
    Q_INVOKABLE void removePlate(int i);
    Q_INVOKABLE int plateSize(int i) const;
    /** Moves the elements to another plate; stays on the current one. One undo step. */
    void moveToPlate(const QStringList& ids, int target);

signals:
    /** After any change to the project, including undo and load. */
    void changed();
    void titleChanged();
    void dirtyChanged();
    void filePathChanged();
    void historyChanged();
    void selectionChanged();
    void activeLayerChanged();
    /** The whole project was replaced (load, reset). */
    void replaced();

private:
    void pushPast(const State& s);
    void noteList(const std::shared_ptr<ElementList>& before);
    void afterChange(bool titleWas);
    void setDirty(bool v);
    void rebuildIndex() const;
    void applySelectionFilter();
    void setSelectionInternal(QStringList ids);
    void ensureActiveLayer();
    void fromModel(lumacut::Document&& d);
    void mutateElementsIn(State& s, const QStringList& ids, const std::function<void(lumacut::Element&)>& fn);
    qint64 stepCost(const State& older, const State& newer) const;
    bool matchesSaved() const;

    struct Step { State state; qint64 cost = 0; };
    State m_state;
    State m_saved;
    std::vector<Step> m_past;
    std::vector<Step> m_future;
    qint64 m_historyBytes = 0;
    bool m_dirty = false;
    QString m_filePath;
    QStringList m_selection;
    QSet<QString> m_selectionSet;
    QString m_activeLayer;
    quint64 m_revision = 0;

    mutable std::shared_ptr<const lumacut::Document> m_built;
    mutable QHash<QString, int> m_index;
    mutable bool m_indexValid = false;
    bool m_sameIds = false;
};
