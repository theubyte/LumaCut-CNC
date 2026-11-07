#pragma once
#include <QImage>
#include <QObject>
#include <QPointF>
#include <QQuickItem>
#include <QStringList>
#include <QTransform>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include <optional>
#include <vector>
#include "Singleton.h"
#include "core/curves.h"
#include "core/model.h"
#include "doc/Document.h"

/** One element of the active plate as the editor sees it: world box and warning stay cached between commits. */
struct SceneItem {
    Document::ElementPtr e;
    quint64 sid = 0;              // stable id for the GPU stage
    lumacut::Box box;
    bool hasBox = false;
    int layer = -1;               // index into Document::layers()
    quint8 warn = 0;              // 0 none, 1 over the work area, 2 park corner or locked strip
};
struct SceneDelta {
    std::vector<int> upserts;     // new or changed shape
    std::vector<int> moved;       // only the transform changed
    std::vector<quint64> removed;
};
struct SelFrame {
    QPointF corners[4];
    double rot = 0;
    QPointF center;
    bool single = false;
    bool valid = false;
};
struct WarnBox { lumacut::Box box; int kind = 0; };

/**
 * The design editor's state and every user action on the design, each one undo step. What is not part of the project
 * (tool, snapping, background, camera image) stays here and never reaches the file. MotivStage does the mouse, the panels
 * in features/motiv read properties here.
 */
class Editor : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Editor)
    Q_PROPERTY(QString tool READ tool WRITE setTool NOTIFY toolChanged)
    Q_PROPERTY(QString hint READ hint NOTIFY toolChanged)
    Q_PROPERTY(bool snapGrid READ snapGrid WRITE setSnapGrid NOTIFY prefsChanged)
    Q_PROPERTY(bool snapObjects READ snapObjects WRITE setSnapObjects NOTIFY prefsChanged)
    Q_PROPERTY(bool lockAspect READ lockAspect WRITE setLockAspect NOTIFY prefsChanged)
    Q_PROPERTY(QVariantMap sel READ sel NOTIFY selChanged)
    Q_PROPERTY(QVariantMap stats READ stats NOTIFY statsChanged)
    Q_PROPERTY(QStringList layerIds READ layerIds NOTIFY layerIdsChanged)
    Q_PROPERTY(int layersRev READ layersRev NOTIFY layersRevChanged)
    Q_PROPERTY(QString processValue READ processValue NOTIFY layersRevChanged)
    Q_PROPERTY(bool cutNotLast READ cutNotLast NOTIFY layersRevChanged)
    Q_PROPERTY(QVariantList plateCounts READ plateCounts NOTIFY statsChanged)
    Q_PROPERTY(QVariantList warnings READ warningsList NOTIFY warningsChanged)
    Q_PROPERTY(bool plateEmpty READ plateEmpty NOTIFY statsChanged)
    Q_PROPERTY(QString dialog READ dialog WRITE setDialog NOTIFY dialogChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString busyText READ busyText NOTIFY busyChanged)
    Q_PROPERTY(QString mouseText READ mouseText NOTIFY mouseChanged)
    Q_PROPERTY(double bedW READ bedW NOTIFY bedChanged)
    Q_PROPERTY(double bedH READ bedH NOTIFY bedChanged)
    Q_PROPERTY(double parkX READ parkLeft NOTIFY bedChanged)
    Q_PROPERTY(double parkW READ parkW NOTIFY bedChanged)
    Q_PROPERTY(double parkH READ parkH NOTIFY bedChanged)
    Q_PROPERTY(QString parkName READ parkName NOTIFY bedChanged)
    Q_PROPERTY(QString bedLabel READ bedLabel NOTIFY bedChanged)
    Q_PROPERTY(bool bgOn READ bgOn WRITE setBgOn NOTIFY backgroundChanged)
    Q_PROPERTY(bool bgLoaded READ bgLoaded NOTIFY backgroundChanged)
    Q_PROPERTY(bool bgBusy READ bgBusy NOTIFY backgroundChanged)
    Q_PROPERTY(double bgAlpha READ bgAlpha WRITE setBgAlpha NOTIFY backgroundChanged)
    Q_PROPERTY(bool hasClipboard READ hasClipboard NOTIFY clipboardChanged)
public:
    explicit Editor(QObject* parent);

    // --- Scene, for MotivStage ---
    const std::vector<SceneItem>& items() const { return m_items; }
    const std::vector<int>& selectedItems() const { return m_selIdx; }
    const SelFrame& selFrame() const { return m_frame; }
    std::optional<lumacut::Box> selectionBox() const;
    const std::vector<WarnBox>& warningBoxes() const { return m_warnBoxes; }
    /** Top-most under a point, or -1: outlines win over fills, among fills the smallest. */
    int hitTest(lumacut::Pt world, double tolMm) const;
    std::vector<int> expandGroup(int item) const;
    bool editableItem(int item) const;
    std::vector<lumacut::CurvePath> curvesOf(const lumacut::Element& e) const;
    /** Selected single element the node tool works on, or -1. */
    int nodeItem() const;
    QImage background() const { return m_bgImage; }
    /** The camera scan from the Pi or from a scan here; show switches it on. */
    void setBackground(QImage img, bool show) { m_bgImage = std::move(img); m_bgOn = show && !m_bgImage.isNull(); emit backgroundChanged(); }
    bool bgOn() const { return m_bgOn; }
    double bgAlpha() const { return m_bgAlpha; }
    static QTransform matrixOf(const lumacut::Transform& t);
    static QTransform imageMatrixOf(const lumacut::Element& e);
    /** During a drag the panel shows where the selection would land. */
    void setLiveBox(std::optional<lumacut::Box> box);
    void setMouse(std::optional<lumacut::Pt> mm);
    std::optional<lumacut::Pt> mouse() const { return m_mouse; }

    // --- Results of the stage's drags, each one undo step (or a mutate after a checkpoint) ---
    void applyMove(double dx, double dy, bool afterCheckpoint);
    void applyScale(lumacut::Pt anchor, double kx, double ky, bool single);
    void applyRotate(lumacut::Pt center, double deg);
    void applyCurves(const QString& id, const std::vector<lumacut::CurvePath>& curves, bool undoStep);
    void spawnCopies();
    void addDrawn(const QString& kind, const lumacut::CurvePath& path);
    void addRect(const lumacut::Box& b);
    void addEllipse(const lumacut::Box& b);
    void addTextAt(lumacut::Pt at);
    void selectItems(const std::vector<int>& items);
    void addToSelection(const std::vector<int>& items);
    void removeFromSelection(const std::vector<int>& items);

    QString tool() const { return m_tool; }
    void setTool(const QString& t);
    QString hint() const;
    bool snapGrid() const { return m_snapGrid; }
    void setSnapGrid(bool v);
    bool snapObjects() const { return m_snapObjects; }
    void setSnapObjects(bool v);
    bool lockAspect() const { return m_lockAspect; }
    void setLockAspect(bool v);
    QVariantMap sel() const { return m_sel; }
    QVariantMap stats() const { return m_stats; }
    QStringList layerIds() const { return m_layerIds; }
    int layersRev() const { return m_layersRev; }
    QString processValue() const { return m_processValue; }
    bool cutNotLast() const { return m_cutNotLast; }
    QVariantList plateCounts() const { return m_plateCounts; }
    QVariantList warningsList() const;
    bool plateEmpty() const { return m_items.empty(); }
    QString dialog() const { return m_dialog; }
    void setDialog(const QString& v) { if (v != m_dialog) { m_dialog = v; emit dialogChanged(); } }
    bool busy() const { return !m_busyText.isEmpty(); }
    QString busyText() const { return m_busyText; }
    QString mouseText() const { return m_mouseText; }
    double bedW() const;
    double bedH() const;
    double parkLeft() const;
    double parkW() const;
    double parkH() const;
    QString parkName() const;
    QString bedLabel() const;
    bool bgLoaded() const { return !m_bgImage.isNull(); }
    bool bgBusy() const { return m_bgBusy; }
    void setBgOn(bool v) { if (v != m_bgOn) { m_bgOn = v; emit backgroundChanged(); } }
    void setBgAlpha(double v) { if (v != m_bgAlpha) { m_bgAlpha = v; emit backgroundChanged(); } }
    bool hasClipboard() const { return !m_clipboard.empty(); }

    // --- Actions for the panels ---
    /** rev: pass Editor.layersRev, so a binding re-reads the row whenever it changed. */
    Q_INVOKABLE QVariantMap layerRow(const QString& id, int rev = 0) const;
    Q_INVOKABLE void pickProcess(const QString& name);
    Q_INVOKABLE void setLayerValue(const QString& id, const QString& key, const QVariant& value);
    Q_INVOKABLE void setLayerProcess(const QString& id, const QString& process);
    Q_INVOKABLE void addLayer();
    Q_INVOKABLE void deleteLayer(const QString& id);
    Q_INVOKABLE void moveLayer(const QString& id, const QString& beforeId);
    Q_INVOKABLE void moveSelectionToLayer(const QString& id);
    Q_INVOKABLE QVariantList layerMenu() const;

    Q_INVOKABLE void align(const QString& mode);
    Q_INVOKABLE void distribute(bool horizontal);
    Q_INVOKABLE void mirror(bool horizontal);
    Q_INVOKABLE void booleanSel(const QString& op);
    Q_INVOKABLE void group();
    Q_INVOKABLE void ungroup();
    Q_INVOKABLE void splitSel();
    Q_INVOKABLE void textToPaths();
    Q_INVOKABLE void duplicate();
    Q_INVOKABLE void copySel();
    Q_INVOKABLE void cutSel();
    Q_INVOKABLE void paste();
    Q_INVOKABLE void deleteSel();
    Q_INVOKABLE void selectAll();
    Q_INVOKABLE void toFront(bool front);
    Q_INVOKABLE void nudge(double dx, double dy);
    Q_INVOKABLE void setPosX(double v);
    Q_INVOKABLE void setPosY(double v);
    Q_INVOKABLE void setSizeW(double v);
    Q_INVOKABLE void setSizeH(double v);
    Q_INVOKABLE void setRotation(double deg);
    Q_INVOKABLE void rotateBy90();
    Q_INVOKABLE void centerInWork();
    Q_INVOKABLE void keepInside();

    Q_INVOKABLE void typeText(const QString& text);
    Q_INVOKABLE void endTextEdit() { m_textEditing = false; }
    Q_INVOKABLE void setFontFamily(const QString& family);
    Q_INVOKABLE void setFontSize(double mm);
    Q_INVOKABLE void setBold(bool on);
    Q_INVOKABLE QStringList fontFamilies() const;
    Q_INVOKABLE QString fontLabel(const QString& family) const;

    Q_INVOKABLE void setImageMode(const QString& mode);
    Q_INVOKABLE void adjustImage(const QString& field, int value);
    Q_INVOKABLE void adjustDone() { m_adjusting = false; }
    Q_INVOKABLE void setImageInvert(bool on);
    Q_INVOKABLE void makeContour(double offsetMm, bool removeSource, bool outerOnly);
    Q_INVOKABLE void vectorizeSel(int threshold, bool invert, bool smooth, bool outerOnly, bool removeSource);

    Q_INVOKABLE void setPlate(int i);
    Q_INVOKABLE void addPlate();
    Q_INVOKABLE void deletePlate(int i);
    Q_INVOKABLE void moveSelectionToPlate(int target);

    Q_INVOKABLE QStringList importFilters() const;
    /** Imports files by path on a worker; the new elements are one undo step and selected. */
    Q_INVOKABLE void importPaths(const QStringList& paths);
    Q_INVOKABLE void importPath(const QString& path) { importPaths({path}); }
    /** Native dialog, thin shell in MvDialogs. onlyImages: for the tool key I. */
    Q_INVOKABLE void askImport(bool onlyImages = false) { emit importRequested(onlyImages); }
    Q_INVOKABLE void askExport(const QString& format) { emit exportRequested(format); }
    Q_INVOKABLE QVariantMap exportInfo(const QString& format) const;
    Q_INVOKABLE QString exportFileName(const QString& format) const;
    /** Writes the active plate on a worker; says the result in a toast. */
    Q_INVOKABLE void exportTo(const QString& path, const QString& format);

    Q_INVOKABLE void loadBackground();
    /** Hands the selected picture to a ComputeImage item in the panel. */
    Q_INVOKABLE void showImageIn(QQuickItem* item) const;

    /** Test bench: replaces the project with n small closed paths on all three layers. */
    Q_INVOKABLE int stress(int n);
    /** Test bench: a rich sample: text, shapes, a picture, all layers. */
    Q_INVOKABLE void sample();
    /** Test bench: elements by index in plain values. */
    Q_INVOKABLE QVariantMap elementInfo(int index) const;

signals:
    void toolChanged();
    void prefsChanged();
    void selChanged();
    void statsChanged();
    void layerIdsChanged();
    void layersRevChanged();
    void warningsChanged();
    void dialogChanged();
    void busyChanged();
    void mouseChanged();
    void bedChanged();
    void backgroundChanged();
    void clipboardChanged();
    void importRequested(bool onlyImages);
    void exportRequested(const QString& format);
    void focusTextRequested();
    // for MotivStage
    void sceneReset();
    void sceneChanged(const SceneDelta& d);
    void selectionResolved();
    void stageLayersChanged();

private:
    void onDocChanged();
    void onSelectionChanged();
    void rebuildAll();
    void fillItem(SceneItem& it, const Document::ElementPtr& e) const;
    void updateItem(SceneItem& it, const Document::ElementPtr& e, bool sameShape) const;
    void assignLayers();
    void resolveSelection();
    void refreshSel();
    void refreshLayers();
    void refreshStats();
    void refreshWarnings();
    void refreshFrame();
    void onBedChanged();
    int layerIndexOf(const QString& id) const;
    QStringList selectedIds() const { return Document::instance()->selection(); }
    std::vector<Document::ElementPtr> selectedElements() const;
    std::optional<lumacut::Box> boxOfItems(const std::vector<int>& idx) const;
    void applyOffsets(const QHash<QString, lumacut::Pt>& off);
    void setSize(std::optional<double> w, std::optional<double> h);
    void updateText(const std::function<void(lumacut::Element&)>& change, bool undoStep);
    void setBusy(const QString& text);
    template <class R> void work(const QString& what, std::function<R()> job, std::function<void(R&&)> done);

    std::vector<SceneItem> m_items;
    std::shared_ptr<Document::ElementList> m_lastList;
    std::shared_ptr<std::vector<lumacut::Layer>> m_lastLayers;
    int m_lastPlate = -1;
    QHash<QString, quint64> m_sids;
    std::vector<int> m_docToItem;      // document index to item index, -1 = another plate
    QHash<QString, int> m_itemOf;
    bool m_itemOfValid = false;
    QHash<QString, int> m_usage;       // elements per layer, all plates
    bool m_usageDirty = true;
    std::vector<int> m_counts;         // elements per plate
    bool m_countsDirty = true;
    quint64 m_nextSid = 100;
    std::vector<int> m_selIdx;
    SelFrame m_frame;
    std::vector<WarnBox> m_warnBoxes;
    std::optional<lumacut::Box> m_liveBox;

    QString m_tool = QStringLiteral("select");
    bool m_snapGrid = true, m_snapObjects = true, m_lockAspect = true;
    QVariantMap m_sel, m_stats;
    QStringList m_layerIds;
    QHash<QString, QVariantMap> m_layerRows;
    int m_layersRev = 0;
    QString m_processValue;
    bool m_cutNotLast = false;
    QVariantList m_plateCounts;
    QString m_dialog;
    QString m_busyText;
    QString m_mouseText = QStringLiteral("X –  Y –");
    std::optional<lumacut::Pt> m_mouse;
    QImage m_bgImage;
    bool m_bgOn = false, m_bgBusy = false;
    double m_bgAlpha = 0.7;
    std::vector<Document::ElementPtr> m_clipboard;
    double m_pasteShift = 0;
    bool m_textEditing = false, m_adjusting = false;
};
