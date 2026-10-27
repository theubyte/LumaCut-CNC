package de.millione.lumacut.app.workspace

import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.MarkerCanvas
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.IconBtn
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.core.DotGrid
import de.millione.lumacut.core.Pt
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Head camera calibration. Recommended: a lasered dot grid, found
 * automatically, which also measures the wide-angle lens distortion.
 * Fallback: four corners of a lasered rectangle set by hand (no lens model).
 */
@Composable
internal fun CalibrationDialog(machine: MachineViewModel, ws: WorkspaceViewModel, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    val busy by machine.busy.collectAsStateWithLifecycle()
    var grid by remember { mutableStateOf(true) }
    var photo by remember { mutableStateOf<Bitmap?>(null) }
    var loading by remember { mutableStateOf(false) }
    var live by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<DotGrid.Result?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var evaluating by remember { mutableStateOf(false) }
    val markers = remember { mutableStateListOf<Offset>() }

    suspend fun fetch() {
        val c = machine.clientOrNotify() ?: run { live = false; return }
        val bmp = ws.snapshot(c)
        if (markers.size != 4 || photo?.width != bmp.width) {
            markers.clear()
            val w = bmp.width.toFloat(); val h = bmp.height.toFloat()
            markers.addAll(listOf(Offset(w * .3f, h * .3f), Offset(w * .7f, h * .3f), Offset(w * .7f, h * .7f), Offset(w * .3f, h * .7f)))
        }
        photo = bmp; result = null; problem = null
    }
    fun grab() {
        loading = true
        scope.launch {
            try { fetch() } catch (e: Exception) { machine.notify(e.message ?: "Kein Kamerabild", true) } finally { loading = false }
        }
    }
    // live picture for turning the lens into focus
    LaunchedEffect(live) {
        while (live) {
            try { fetch() } catch (e: Exception) { machine.notify(e.message ?: "Kein Kamerabild", true); live = false }
            delay(300)
        }
    }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Row(Modifier.fillMaxSize().background(Lc.bg).padding(20.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            LcCard(Modifier.width(400.dp).fillMaxHeight()) {
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    Text("Kopfkamera kalibrieren", style = LcTypography.headlineSmall)
                    Spacer(Modifier.height(8.dp))
                    Segmented(listOf(true to "Punktraster (genau)", false to "4 Ecken (einfach)"), grid, { grid = it; result = null; problem = null }, Modifier.fillMaxWidth())
                    Spacer(Modifier.height(10.dp))
                    if (grid) {
                        SmallText("Misst auch die Weitwinkel-Verzerrung der Linse heraus – damit stimmt der Scan bis an den Bildrand.\n\n" +
                            "1. Restplatte (mind. 21 × 17 cm) in die Mitte legen, Fokus messen, Punktraster lasern (ca. 5 min).\n" +
                            "2. Z auf die Höhe fahren, in der gescannt wird, und den Kopf über das Raster fahren.\n" +
                            "3. Live-Bild an und das Objektiv von Hand drehen, bis die Punkte scharf sind. Das Raster soll das Bild füllen, der große Punkt in der Mitte.\n" +
                            "4. Auswerten und speichern. Danach Z und Objektiv nicht mehr verstellen.")
                        Spacer(Modifier.height(12.dp))
                        LcButton("1 · Punktraster an Laser senden", { ws.sendGridJob(machine) }, Modifier.fillMaxWidth(), LcIcons.send, busy = "upload" in busy)
                        Spacer(Modifier.height(8.dp))
                        LcButton("2 · Kopf über das Raster", { ws.headOverGrid(machine) }, Modifier.fillMaxWidth(), LcIcons.machine, busy = "moveto" in busy)
                    } else {
                        SmallText("1. Kalibrier-Rechteck (60 × 40 mm, Mitte des Arbeitsbereichs) auf Restmaterial lasern.\n2. Kopf darüber fahren, bis das ganze Rechteck im Bild ist.\n" +
                            "3. Die vier Marker auf die nummerierten Ecken ziehen.\n4. Speichern. Danach nicht mehr in Z verstellen – der Scan nutzt dieselbe Höhe.\nOhne Linsenkorrektur: am Bildrand ungenauer.")
                        Spacer(Modifier.height(12.dp))
                        LcButton("1 · Rechteck an Laser senden", { ws.sendCalibrationJob(machine) }, Modifier.fillMaxWidth(), LcIcons.send, busy = "upload" in busy)
                        Spacer(Modifier.height(8.dp))
                        LcButton("2 · Kopf über das Rechteck", { ws.headOverRect(machine) }, Modifier.fillMaxWidth(), LcIcons.machine, busy = "moveto" in busy)
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        SmallText("XY 10:")
                        IconBtn(LcIcons.left, "X+", { machine.jog('X', 10.0) })
                        IconBtn(LcIcons.right, "X−", { machine.jog('X', -10.0) })
                        IconBtn(LcIcons.up, "Y−", { machine.jog('Y', -10.0) })
                        IconBtn(LcIcons.down, "Y+", { machine.jog('Y', 10.0) })
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        SmallText("Z 1 mm:")
                        IconBtn(LcIcons.up, "Z+", { machine.jog('Z', 1.0) })
                        IconBtn(LcIcons.down, "Z−", { machine.jog('Z', -1.0) })
                        SmallText(machine.status.value?.position?.getOrNull(2)?.let { "Z %.1f".format(it) } ?: "", Lc.faint)
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        LcButton("Kamerabild", { grab() }, Modifier.weight(1f), LcIcons.camera, busy = loading, enabled = !live)
                        LcButton(if (live) "Live aus" else "Live (Schärfe)", { live = !live }, Modifier.weight(1f), LcIcons.camera,
                            kind = if (live) BtnKind.PRIMARY else BtnKind.GHOST)
                    }
                    if (grid) {
                        Spacer(Modifier.height(8.dp))
                        LcButton("3 · Raster auswerten", {
                            val p = photo ?: return@LcButton
                            live = false; evaluating = true
                            scope.launch {
                                try { result = ws.evaluateGrid(machine, p); problem = null }
                                catch (e: Exception) { result = null; problem = e.message ?: "Auswertung fehlgeschlagen" }
                                finally { evaluating = false }
                            }
                        }, Modifier.fillMaxWidth(), LcIcons.check, BtnKind.PRIMARY, busy = evaluating, enabled = photo != null)
                        result?.let { r ->
                            val u = r.calibration.usable(0.0)
                            Spacer(Modifier.height(8.dp))
                            SmallText("%d Punkte erkannt · Abweichung im Mittel %.2f mm, höchstens %.2f mm\nNutzbares Bildfeld %.0f × %.0f mm · Linse k1 %.3f"
                                .format(r.lens.points, r.lens.rmsMm, r.lens.maxMm, u.width, u.height, r.lens.k1), Lc.accent)
                        }
                        problem?.let { Spacer(Modifier.height(8.dp)); SmallText(it, Lc.warn) }
                    }
                }
                Spacer(Modifier.height(10.dp))
                LcButton("Speichern", {
                    if (grid) result?.let { ws.saveGridCalibration(machine, it); onClose() }
                    else {
                        val p = photo ?: return@LcButton
                        if (ws.saveCalibration(machine, p, markers.map { Pt(it.x.toDouble(), it.y.toDouble()) })) onClose()
                    }
                }, Modifier.fillMaxWidth(), LcIcons.check, BtnKind.PRIMARY,
                    enabled = if (grid) result != null else photo != null && markers.size == 4, big = true)
                Spacer(Modifier.height(8.dp))
                LcButton("Schließen", { live = false; onClose() }, Modifier.fillMaxWidth(), kind = BtnKind.GHOST)
            }
            Box(Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(18.dp)).background(Color(0xFF0B1015)), contentAlignment = Alignment.Center) {
                val p = photo
                when {
                    p == null -> SmallText("Noch kein Kamerabild")
                    grid -> PhotoWithPoints(p, result?.points.orEmpty())
                    else -> MarkerCanvas(p, markers)
                }
            }
        }
    }
}

/** Camera picture with the recognised grid dots marked. */
@Composable
private fun PhotoWithPoints(photo: Bitmap, points: List<Pt>) {
    val image = remember(photo) { photo.asImageBitmap() }
    var size by remember { mutableStateOf(IntSize.Zero) }
    Canvas(Modifier.fillMaxSize().onSizeChanged { size = it }) {
        if (size == IntSize.Zero) return@Canvas
        val k = min(size.width / photo.width.toFloat(), size.height / photo.height.toFloat())
        val org = Offset((size.width - photo.width * k) / 2, (size.height - photo.height * k) / 2)
        drawImage(image, dstOffset = IntOffset(org.x.roundToInt(), org.y.roundToInt()),
            dstSize = IntSize((photo.width * k).roundToInt(), (photo.height * k).roundToInt()))
        for (q in points) drawCircle(Lc.accent, 7f, org + Offset(q.x.toFloat(), q.y.toFloat()) * k, style = Stroke(2.5f))
    }
}
