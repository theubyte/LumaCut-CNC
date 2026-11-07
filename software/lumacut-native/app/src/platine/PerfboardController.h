#pragma once
#include <QObject>
#include <QStringList>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <memory>
#include <vector>
#include "Singleton.h"
#include "core/pcb/perfboard.h"

/**
 * Lochraster mode of the Platine view: a perfboard design (parts on holes, connections, labels), its checks, parts list,
 * assembly assistant and the way into the project. The laser only MARKS the solder mask here; connections are solder
 * bridges or wires, nothing is cut. The design is not part of the shared project (Android would drop unknown fields):
 * it lives in its own `.lumaraster` file plus a local autosave. Markings are computed on a worker.
 * QML: Perfboard.
 */
class PerfboardController : public QObject {
    Q_OBJECT
    QML_NAMED_ELEMENT(Perfboard)
    QML_SINGLETON
    LC_SINGLETON(PerfboardController)
    Q_PROPERTY(int revision READ revision NOTIFY changed)
    Q_PROPERTY(QVariantMap board READ board NOTIFY changed)
    Q_PROPERTY(QVariantList templates READ templates CONSTANT)
    Q_PROPERTY(QVariantList library READ library CONSTANT)
    Q_PROPERTY(QVariantList designTemplates READ designTemplates CONSTANT)
    Q_PROPERTY(QString tool READ tool WRITE setTool NOTIFY toolChanged)
    Q_PROPERTY(QString partId READ partId NOTIFY toolChanged)
    Q_PROPERTY(bool wireSolder READ wireSolder WRITE setWireSolder NOTIFY toolChanged)
    Q_PROPERTY(bool viewBelow READ viewBelow WRITE setViewBelow NOTIFY viewChanged)
    Q_PROPERTY(bool showMarks READ showMarks WRITE setShowMarks NOTIFY viewChanged)
    Q_PROPERTY(QVariantMap selection READ selection NOTIFY selectionChanged)
    Q_PROPERTY(QVariantList parts READ parts NOTIFY changed)
    Q_PROPERTY(QVariantList checks READ checks NOTIFY changed)
    Q_PROPERTY(int badCount READ badCount NOTIFY changed)
    Q_PROPERTY(QVariantList bomRows READ bomRows NOTIFY changed)
    Q_PROPERTY(int assistStep READ assistStep NOTIFY assistChanged)
    Q_PROPERTY(QVariantList assistItems READ assistItems NOTIFY assistChanged)
    Q_PROPERTY(QVariantMap options READ options NOTIFY changed)
    Q_PROPERTY(double bedX READ bedX NOTIFY bedChanged)
    Q_PROPERTY(double bedY READ bedY NOTIFY bedChanged)
    Q_PROPERTY(QString title READ title NOTIFY changed)
    Q_PROPERTY(QString filePath READ filePath NOTIFY changed)
    Q_PROPERTY(bool dirty READ dirty NOTIFY changed)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY changed)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY marksChanged)
    Q_PROPERTY(QString hint READ hint NOTIFY toolChanged)
public:
    explicit PerfboardController(QObject* parent);

    const lumacut::pcb::PerfDesign& design() const { return m_design; }
    std::shared_ptr<const lumacut::pcb::PerfMarks> marks() const { return m_marks; }
    lumacut::pcb::MarkOptions markOptions() const { return m_opt; }

    int revision() const { return m_revision; }
    QVariantMap board() const;
    QVariantList templates() const;
    QVariantList library() const;
    QVariantList designTemplates() const;
    QString tool() const { return m_tool; }
    void setTool(const QString& t);
    QString partId() const { return m_partId; }
    bool wireSolder() const { return m_wireSolder; }
    void setWireSolder(bool v);
    bool viewBelow() const { return m_viewBelow; }
    void setViewBelow(bool v);
    bool showMarks() const { return m_showMarks; }
    void setShowMarks(bool v);
    QVariantMap selection() const;
    QVariantList parts() const;
    QVariantList checks() const { return m_checks; }
    int badCount() const;
    QVariantList bomRows() const;
    int assistStep() const { return m_assist; }
    QVariantList assistItems() const;
    QVariantMap options() const;
    double bedX() const;
    double bedY() const;
    QString title() const { return m_design.title; }
    QString filePath() const { return m_path; }
    bool dirty() const { return m_dirty; }
    bool canUndo() const { return !m_past.empty(); }
    bool canRedo() const { return !m_future.empty(); }
    bool busy() const { return m_running; }
    QString hint() const;

    // Selection as the stage sees it: kind 0 none, 1 part, 2 wire, 3 label.
    int selKind() const { return m_selKind; }
    int selIndex() const { return m_selIndex; }
    /** Part indices highlighted by the assistant. */
    int assistPart() const;
    /** Ghost while placing: a part at a hole or a route from the wire start. */
    struct Ghost { bool on = false; QString partId; lumacut::pcb::GridPt at; int rot = 0; bool wire = false; std::vector<lumacut::pcb::GridPt> route; };
    const Ghost& ghost() const { return m_ghost; }
    /** Temporary offset of the selected part while dragging. */
    lumacut::pcb::GridPt dragOffset() const { return m_drag; }

    // ---- Editing (each one undo step) ----
    Q_INVOKABLE void newDesign(int templateIndex);
    /** Opens a shipped design (e.g. laser-interface-v2) as a new, unsaved design. */
    Q_INVOKABLE bool openTemplate(const QString& id);
    Q_INVOKABLE void setTemplate(int templateIndex);
    Q_INVOKABLE void setBoard(const QString& key, const QVariant& value);
    Q_INVOKABLE void pickPart(const QString& id);
    Q_INVOKABLE QString placePart(const QString& id, int c, int r, int rot = 0);
    Q_INVOKABLE void addWire(int c1, int r1, int c2, int r2, bool solder, bool verticalFirst = false);
    Q_INVOKABLE void addLabel(const QString& text, double x, double y);
    Q_INVOKABLE void select(int kind, int index);
    Q_INVOKABLE void clearSelection() { select(0, -1); }
    Q_INVOKABLE void selectRef(const QString& ref);
    Q_INVOKABLE void moveSelected(int dc, int dr);
    Q_INVOKABLE void rotateSelected();
    Q_INVOKABLE void deleteSelected();
    Q_INVOKABLE void setSelValue(const QString& key, const QVariant& value);
    Q_INVOKABLE void undo();
    Q_INVOKABLE void redo();
    Q_INVOKABLE void setOption(const QString& key, const QVariant& value);
    Q_INVOKABLE void setBed(double x, double y);
    // ---- Stage input (board mm) ----
    void hover(std::optional<lumacut::pcb::GridPt> g, lumacut::Pt p, bool shift);
    void press(std::optional<lumacut::pcb::GridPt> g, lumacut::Pt p, bool shift);
    void dragTo(std::optional<lumacut::pcb::GridPt> g);
    void release();
    Q_INVOKABLE void escape();
    Q_INVOKABLE void rotateGhostOrSelection();
    // ---- Assistant ----
    Q_INVOKABLE void startAssist();
    Q_INVOKABLE void assistGo(int step);
    Q_INVOKABLE void stopAssist();
    Q_INVOKABLE void toggleDone(int step);
    // ---- Files ----
    Q_INVOKABLE void askOpen() { emit fileRequested(QStringLiteral("open")); }
    Q_INVOKABLE void askSave() { emit fileRequested(QStringLiteral("save")); }
    Q_INVOKABLE void askExport(const QString& format) { emit fileRequested(format); }
    Q_INVOKABLE bool save(const QString& path);
    Q_INVOKABLE bool open(const QString& path);
    Q_INVOKABLE bool exportTo(const QString& path, const QString& format);
    Q_INVOKABLE QString suggestedName(const QString& ext) const;
    // ---- Project ----
    Q_INVOKABLE void toProject();
    Q_INVOKABLE QVariantMap info() const;

signals:
    void changed();
    void toolChanged();
    void viewChanged();
    void selectionChanged();
    void assistChanged();
    void bedChanged();
    void marksChanged();
    void ghostChanged();
    void fileRequested(const QString& what);

private:
    void edit(const std::function<void(lumacut::pcb::PerfDesign&)>& fn);
    void afterChange();
    void computeMarks();
    void autosave();
    void place();
    static QString newItemId();
    void setGhost(Ghost g);

    lumacut::pcb::PerfDesign m_design;
    std::vector<lumacut::pcb::PerfDesign> m_past, m_future;
    lumacut::pcb::MarkOptions m_opt;
    double m_power = 10, m_speed = 3000;
    std::shared_ptr<const lumacut::pcb::PerfMarks> m_marks;
    QVariantList m_checks;
    QString m_tool = QStringLiteral("select"), m_partId = QStringLiteral("res-762"), m_path;
    bool m_wireSolder = true, m_viewBelow = false, m_showMarks = true, m_dirty = false;
    int m_selKind = 0, m_selIndex = -1, m_ghostRot = 0;
    int m_revision = 0, m_assist = -1;
    std::vector<bool> m_done;
    std::optional<lumacut::pcb::GridPt> m_wireStart;
    std::optional<lumacut::pcb::GridPt> m_dragFrom;
    lumacut::pcb::GridPt m_drag;
    Ghost m_ghost;
    bool m_running = false, m_again = false;
    QTimer m_marksTimer, m_saveTimer;
    int m_plateTop = -1, m_plateBottom = -1;
};
