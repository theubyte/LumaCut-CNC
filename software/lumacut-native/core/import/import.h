#pragma once
/**
 * Import aller Motive, Schnittstelle für Editor und Oberfläche. Der Dateityp kommt aus dem Inhalt, der Name ist nur ein
 * Hinweis. Reine Logik; nichts davon im Oberflächen-Thread aufrufen (`importFileAsync` oder eigener Worker).
 *
 * Ablauf im Editor:
 *   auto r = importFile(name, bytes, importContextFor(doc, aktiveEbene));
 *   if (!r.ok()) meldeFehler(r.error);
 *   else { doc = applyImport(doc, r); zeige(r.warnings); }
 */
#include "core/model.h"
#include <QFuture>
#include <QString>
#include <QStringList>
#include <vector>

namespace lumacut {

/** Was geschieht, wenn Teile nicht auf eine Platte passen. Auto: wie die Tauri-Fassung (Platten, sonst verkleinern). */
enum class PartialFit { Auto, OnlyFitting, Shrink, Plates };

struct ImportContext {
    std::vector<Layer> layers;      /// Ebenen des Projekts; leer = Standardebenen, die dann in ImportResult::layers stehen
    QString activeLayerId;          /// für Inhalt ohne eigene Ebene; gesperrt, ausgeblendet oder leer = erste beschreibbare
    int activePlate = 0, plateCount = 1;
    PartialFit partial = PartialFit::Auto;
    /** Mehr Formen als das: je Ebene ein Element (mit Warnsatz), damit Auswahl und Rückgängig flüssig bleiben. */
    int maxElements = 20000;
};
ImportContext importContextFor(const Document& doc, const QString& activeLayerId = {});

/** Wie der Import auf die Fläche kam. */
enum class ImportFit {
    AsIs,        /// Originalgröße, mittig (oder neben die Park-Ecke geschoben)
    Packed,      /// Originalgröße, Teile in Reihen angeordnet
    OnlyFitting, /// Originalgröße, partial.units - partial.fitting Teile fehlen
    Shrunk,      /// verkleinert auf partial.shrinkPercent %
    Plates,      /// Originalgröße auf mehrere Platten verteilt
    Image        /// ein Bild, mittig
};

/** Gefüllt, wenn das Motiv nicht auf eine Platte passt: damit kann die Oberfläche nachfragen und neu importieren. */
struct PartialInfo {
    int units = 0, fitting = 0, shrinkPercent = 100;
    int plates = 0;     /// > 1: Verteilen auf so viele Platten ist möglich
    int leftOut = 0;    /// beim Verteilen auf keiner Platte untergebracht
};

struct ImportResult {
    QString error;                  /// ein Satz mit dem nächsten Schritt; leer = gelungen
    QString kind;                   /// "SVG", "xTool Studio", "Bild", ...
    std::vector<Element> elements;  /// fertig auf der Fläche, Platte schon eingetragen
    std::vector<Layer> layers;      /// neue Ebenen, Reihenfolge nach Quelle
    QStringList warnings;           /// ehrlich: was fehlt, was verkleinert wurde, was ausgeblendet ist
    int addedPlates = 0;            /// so viele neue Platten hängt applyImport hinten an
    ImportFit fit = ImportFit::AsIs;
    PartialInfo partial;
    bool ok() const { return error.isEmpty(); }
};

/** Wirft nie, auch nicht bei kaputten Dateien oder zu wenig Speicher: Fehler stehen in `error`. Threadsicher. */
ImportResult importFile(const QString& name, const QByteArray& bytes, const ImportContext& ctx);
/** Liest die Datei und importiert sie. Für Prüfungen und Dateiaktionen mit Pfad. */
ImportResult importPath(const QString& path, const ImportContext& ctx);
/** Läuft im globalen Thread-Pool. */
QFuture<ImportResult> importFileAsync(const QString& name, const QByteArray& bytes, const ImportContext& ctx);

/**
 * Übernimmt das Ergebnis wie Androids addImported: neue Füll-Ebenen hinter "Gravieren", neue Linien-Ebenen ans Ende,
 * neue Platten hinten an. Die Auswahl der neuen Elemente ist Sache des Editors.
 */
Document applyImport(const Document& doc, const ImportResult& r);

/** Für den Dateidialog: "Alle Motive (*.svg *.dxf ...)", dann je Format. */
QStringList importFilters();
QStringList importExtensions();

}  // namespace lumacut
