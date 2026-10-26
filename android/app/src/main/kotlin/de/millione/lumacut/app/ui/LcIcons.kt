package de.millione.lumacut.app.ui

import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/** Line icons on a 24 grid, drawn as strokes and tinted by Icon(). */
object LcIcons {
    private fun icon(name: String, vararg paths: String): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            for (d in paths) addPath(
                pathData = PathParser().parsePathString(d).toNodes(),
                stroke = SolidColor(Color.White), strokeLineWidth = 1.9f,
                strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
            )
        }.build()

    val machine = icon("machine", "M5 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M8 20h8M12 16v4M7 8h6M7 12h3")
    val jobs = icon("jobs", "M4 6h16M4 12h16M4 18h10")
    val editor = icon("editor", "M4 20l4-1 11-11-3-3L5 16l-1 4z", "M14 6l3 3")
    val material = icon("material", "M3 7l9-4 9 4-9 4-9-4z", "M3 12l9 4 9-4", "M3 17l9 4 9-4")
    val settings = icon("settings", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1")
    val up = icon("up", "M12 19V5M6 11l6-6 6 6")
    val down = icon("down", "M12 5v14M6 13l6 6 6-6")
    val left = icon("left", "M19 12H5M11 6l-6 6 6 6")
    val right = icon("right", "M5 12h14M13 6l6 6-6 6")
    val home = icon("home", "M3 11l9-7 9 7", "M5 10v10h14V10")
    val probe = icon("probe", "M12 3v10", "M9 10l3 3 3-3", "M4 20h16")
    val park = icon("park", "M4 20V4", "M4 20h16", "M8 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4z")
    val light = icon("light", "M9 18h6M10 21h4", "M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z")
    val fan = icon("fan", "M12 10c0-4 1-7 4-7 2 0 2 3 0 5M14 12c4 0 7 1 7 4 0 2-3 2-5 0M12 14c0 4-1 7-4 7-2 0-2-3 0-5M10 12c-4 0-7-1-7-4 0-2 3-2 5 0")
    val refresh = icon("refresh", "M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7")
    val upload = icon("upload", "M12 16V4M7 9l5-5 5 5", "M4 20h16")
    val trash = icon("trash", "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13")
    val play = icon("play", "M7 4l13 8-13 8z")
    val stop = icon("stop", "M6 6h12v12H6z")
    val select = icon("select", "M5 3l14 8-6 2-2 6z")
    val rect = icon("rect", "M4 6h16v12H4z")
    val ellipse = icon("ellipse", "M12 5c4.4 0 8 3.1 8 7s-3.6 7-8 7-8-3.1-8-7 3.6-7 8-7z")
    val line = icon("line", "M5 19L19 5")
    val polygon = icon("polygon", "M12 3l8 6-3 10H7L4 9z")
    val pen = icon("pen", "M3 17c3-6 6 2 9-4s5-6 9-5")
    val text = icon("text", "M5 6V4h14v2", "M12 4v16M9 20h6")
    val image = icon("image", "M4 5h16v14H4z", "M4 15l5-5 5 5 2-2 4 4", "M15 9h.01")
    val svg = icon("svg", "M6 3h9l5 5v13H6z", "M14 3v6h6", "M9 15l2 2 4-4")
    val camera = icon("camera", "M4 8h3l2-3h6l2 3h3v11H4z", "M12 16a3 3 0 1 0 0-6 3 3 0 0 0 0 6z")
    val undo = icon("undo", "M9 14L4 9l5-5", "M4 9h11a5 5 0 0 1 0 10h-3")
    val redo = icon("redo", "M15 14l5-5-5-5", "M20 9H9a5 5 0 0 0 0 10h3")
    val copy = icon("copy", "M8 8h12v12H8z", "M16 8V4H4v12h4")
    val layers = material
    val plus = icon("plus", "M12 5v14M5 12h14")
    val send = icon("send", "M4 12l16-8-6 16-2-7z")
    val save = icon("save", "M5 4h11l3 3v13H5z", "M8 4v5h7V4", "M8 20v-6h8v6")
    val folder = icon("folder", "M3 6h6l2 2h10v11H3z")
    val center = icon("center", "M12 3v18M3 12h18", "M8 8h8v8H8z")
    val eye = icon("eye", "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z")
    val eyeOff = icon("eyeOff", "M3 3l18 18", "M10.6 6.1A10 10 0 0 1 12 6c6 0 10 6 10 6a17 17 0 0 1-3.2 3.9M6.1 7.5A17 17 0 0 0 2 12s4 6 10 6c1.6 0 3-.4 4.3-1")
    val close = icon("close", "M6 6l12 12M18 6L6 18")
    val check = icon("check", "M5 12l5 5 9-10")
    val warn = icon("warn", "M12 3l10 18H2z", "M12 10v4M12 17h.01")
    val group = icon("group", "M4 4h7v7H4z", "M13 13h7v7h-7z", "M11 7h5v6")
    val ungroup = icon("ungroup", "M4 4h7v7H4z", "M13 13h7v7h-7z")
    val lock = icon("lock", "M6 11h12v9H6z", "M9 11V8a3 3 0 0 1 6 0v3")
    val unlock = icon("unlock", "M6 11h12v9H6z", "M9 11V8a3 3 0 0 1 5.8-1")
    val rotate = icon("rotate", "M20 12a8 8 0 1 1-2.3-5.7", "M20 4v5h-5")
    val multi = icon("multi", "M4 4h10v10H4z", "M10 10h10v10H10z")
    val laser = icon("laser", "M12 2v6", "M8 8h8l-2 4h-4z", "M12 14v8M9 19l3 3 3-3")
    val scan = icon("scan", "M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4", "M7 12h10")
    val mesh = icon("mesh", "M4 6h16M4 12h16M4 18h16", "M8 4v16M16 4v16")
    val workflow = icon("workflow", "M5 5h4v4H5z", "M15 15h4v4h-4z", "M9 7h6a2 2 0 0 1 2 2v6")
}
