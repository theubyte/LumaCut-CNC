#include "core/pcb/layers.h"

#include <QHash>
#include <QRegularExpression>
#include <utility>
#include <vector>

namespace lumacut::pcb {

QString layerLabel(LayerKind k) {
    switch (k) {
    case LayerKind::CopperTop: return QStringLiteral("Kupfer oben");
    case LayerKind::CopperBottom: return QStringLiteral("Kupfer unten");
    case LayerKind::CopperInner: return QStringLiteral("Kupfer innen (ungenutzt)");
    case LayerKind::MaskTop: return QStringLiteral("Lötstopp oben");
    case LayerKind::MaskBottom: return QStringLiteral("Lötstopp unten");
    case LayerKind::SilkTop: return QStringLiteral("Bestückungsdruck oben");
    case LayerKind::SilkBottom: return QStringLiteral("Bestückungsdruck unten");
    case LayerKind::PasteTop: return QStringLiteral("Lötpaste oben (ungenutzt)");
    case LayerKind::PasteBottom: return QStringLiteral("Lötpaste unten (ungenutzt)");
    case LayerKind::Outline: return QStringLiteral("Umriss");
    case LayerKind::Drill: return QStringLiteral("Bohrungen");
    case LayerKind::Other: break;
    }
    return QStringLiteral("Nicht verwenden");
}

QString layerKey(LayerKind k) {
    static const char* keys[] = {"copper-top", "copper-bottom", "copper-inner", "mask-top", "mask-bottom", "silk-top",
                                 "silk-bottom", "paste-top", "paste-bottom", "outline", "drill", "other"};
    return QString::fromLatin1(keys[int(k)]);
}
LayerKind layerFromKey(const QString& key) {
    for (int i = 0; i < kLayerKindCount; ++i) if (layerKey(LayerKind(i)) == key) return LayerKind(i);
    return LayerKind::Other;
}

LayerKind kindFromFileFunction(const QString& f) {
    const QStringList p = f.split(QLatin1Char(','));
    int side = 0;   // 1 top, 2 bottom
    for (const QString& s : p) {
        if (s.compare(QLatin1String("top"), Qt::CaseInsensitive) == 0) { side = 1; break; }
        if (s.startsWith(QLatin1String("bot"), Qt::CaseInsensitive)) { side = 2; break; }
    }
    const QString k = p.value(0).toLower();
    if (k == QLatin1String("copper")) return side == 1 ? LayerKind::CopperTop : side == 2 ? LayerKind::CopperBottom : LayerKind::CopperInner;
    if (k == QLatin1String("soldermask") && side) return side == 1 ? LayerKind::MaskTop : LayerKind::MaskBottom;
    if (k == QLatin1String("legend") && side) return side == 1 ? LayerKind::SilkTop : LayerKind::SilkBottom;
    if (k == QLatin1String("paste") && side) return side == 1 ? LayerKind::PasteTop : LayerKind::PasteBottom;
    if (k == QLatin1String("profile")) return LayerKind::Outline;
    if (k == QLatin1String("plated") || k == QLatin1String("nonplated")) return LayerKind::Drill;
    return LayerKind::Other;
}

bool looksLikeDrill(std::string_view text) {
    const QString head = QString::fromLatin1(text.substr(0, 4000));
    static const QRegularExpression m48(QStringLiteral("^\\s*M48\\b"), QRegularExpression::MultilineOption);
    static const QRegularExpression tool(QStringLiteral("^\\s*T\\d+C[\\d.]+"), QRegularExpression::MultilineOption);
    return m48.match(head).hasMatch() || (tool.match(head).hasMatch() && !head.contains(QLatin1String("%FS")));
}

LayerKind classifyLayer(const QString& fileName, std::string_view text) {
    QString base = fileName.section(QRegularExpression(QStringLiteral("[\\\\/]")), -1).toLower();
    const qsizetype dot = base.lastIndexOf(QLatin1Char('.'));
    const QString ext = dot >= 0 ? base.mid(dot + 1) : QString();
    const QString stem = dot >= 0 ? base.left(dot) : base;

    static const QStringList ignored = {"gbrjob", "pdf", "png", "jpg", "zip", "rpt", "csv", "pos", "html", "md"};
    if (ignored.contains(ext)) return LayerKind::Other;
    if (!text.empty()) {
        static const QRegularExpression tf(QStringLiteral("(?:%|#@!\\s*)TF\\.FileFunction,([^*]*)\\*"));
        const auto m = tf.match(QString::fromLatin1(text.substr(0, 65536)));
        if (m.hasMatch()) {
            const LayerKind k = kindFromFileFunction(m.captured(1));
            if (k != LayerKind::Other) return k;
        }
    }
    static const QRegularExpression gm(QStringLiteral("^gm\\d+$")), gn(QStringLiteral("^gp?\\d+$"));
    if (gm.match(ext).hasMatch()) return LayerKind::Outline;
    if (gn.match(ext).hasMatch()) return LayerKind::CopperInner;
    static const QHash<QString, LayerKind> exts = {
        {"gtl", LayerKind::CopperTop}, {"cmp", LayerKind::CopperTop}, {"top", LayerKind::CopperTop},
        {"gbl", LayerKind::CopperBottom}, {"sol", LayerKind::CopperBottom}, {"bot", LayerKind::CopperBottom},
        {"gts", LayerKind::MaskTop}, {"stc", LayerKind::MaskTop}, {"smt", LayerKind::MaskTop},
        {"gbs", LayerKind::MaskBottom}, {"sts", LayerKind::MaskBottom}, {"smb", LayerKind::MaskBottom},
        {"gto", LayerKind::SilkTop}, {"plc", LayerKind::SilkTop}, {"sst", LayerKind::SilkTop},
        {"gbo", LayerKind::SilkBottom}, {"pls", LayerKind::SilkBottom}, {"ssb", LayerKind::SilkBottom},
        {"gtp", LayerKind::PasteTop}, {"crc", LayerKind::PasteTop}, {"gbp", LayerKind::PasteBottom}, {"crs", LayerKind::PasteBottom},
        {"gko", LayerKind::Outline}, {"gml", LayerKind::Outline}, {"dim", LayerKind::Outline}, {"oln", LayerKind::Outline},
        {"out", LayerKind::Outline}, {"bor", LayerKind::Outline},
        {"drl", LayerKind::Drill}, {"xln", LayerKind::Drill}, {"exc", LayerKind::Drill}, {"drd", LayerKind::Drill},
        {"tap", LayerKind::Drill}, {"ncd", LayerKind::Drill},
    };
    if (auto it = exts.find(ext); it != exts.end()) return *it;
    // Name fragments of KiCad, EasyEDA, Eagle and Altium exports. Order matters: mask before copper.
    static const std::vector<std::pair<QRegularExpression, LayerKind>> rules = {
        {QRegularExpression(QStringLiteral("edge[._-]?cuts|board[._ -]?outline|outline|umriss|profile|keep[._-]?out")), LayerKind::Outline},
        {QRegularExpression(QStringLiteral("(^|[^a-z])(pth|npth)([^a-z]|$)|drill|bohr")), LayerKind::Drill},
        {QRegularExpression(QStringLiteral("f[._]?(mask|sm)\\b|top[._ -]?(solder[._ -]?)?mask|solder[._ -]?mask[._ -]?top|mask[._ -]?top")), LayerKind::MaskTop},
        {QRegularExpression(QStringLiteral("b[._]?(mask|sm)\\b|bot(tom)?[._ -]?(solder[._ -]?)?mask|solder[._ -]?mask[._ -]?bot|mask[._ -]?bot")), LayerKind::MaskBottom},
        {QRegularExpression(QStringLiteral("f[._]?paste|top[._ -]?paste|paste[._ -]?top")), LayerKind::PasteTop},
        {QRegularExpression(QStringLiteral("b[._]?paste|bot(tom)?[._ -]?paste|paste[._ -]?bot")), LayerKind::PasteBottom},
        {QRegularExpression(QStringLiteral("f[._]?silk|top[._ -]?silk|silk[._ -]?top|top[._ -]?overlay")), LayerKind::SilkTop},
        {QRegularExpression(QStringLiteral("b[._]?silk|bot(tom)?[._ -]?silk|silk[._ -]?bot|bot(tom)?[._ -]?overlay")), LayerKind::SilkBottom},
        {QRegularExpression(QStringLiteral("in\\d+[._]?cu|inner")), LayerKind::CopperInner},
        {QRegularExpression(QStringLiteral("f[._]cu\\b|top[._ -]?(layer|copper)|copper[._ -]?top")), LayerKind::CopperTop},
        {QRegularExpression(QStringLiteral("b[._]cu\\b|bot(tom)?[._ -]?(layer|copper)|copper[._ -]?bot")), LayerKind::CopperBottom},
    };
    for (const auto& [re, kind] : rules) if (re.match(stem).hasMatch()) return kind;
    if (!text.empty() && looksLikeDrill(text)) return LayerKind::Drill;
    if (text.empty() && (ext == QLatin1String("txt") || ext == QLatin1String("nc") || ext == QLatin1String("cnc"))) return LayerKind::Drill;
    return LayerKind::Other;
}

}  // namespace lumacut::pcb
