package de.millione.lumacut.app.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorScreen
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.Notice
import de.millione.lumacut.app.machine.headline

/** The main path is 1 Material → 2 Motiv → 3 Starten; everything else lives under Maschine. */
enum class Dest(val label: String, val icon: ImageVector, val step: Int? = null) {
    MATERIAL("Material", LcIcons.material, 1),
    MOTIV("Motiv", LcIcons.editor, 2),
    START("Starten", LcIcons.play, 3),
    MASCHINE("Maschine", LcIcons.machine),
    EINSTELLUNGEN("Einstellungen", LcIcons.settings),
}

@Composable
fun LumaCutApp(machine: MachineViewModel, editor: EditorViewModel) {
    var dest by rememberSaveable { mutableStateOf(if (editor.materialKey.value == null) Dest.MATERIAL else Dest.MOTIV) }
    var machineTab by rememberSaveable { mutableStateOf(MachineTab.STEUERUNG) }
    val snackbar = remember { SnackbarHostState() }
    var lastNotice by remember { mutableStateOf<Notice?>(null) }
    LaunchedEffect(Unit) {
        machine.notices.collect { n -> lastNotice = n; snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(n.text) }
    }
    LaunchedEffect(Unit) { editor.notices.collect { n -> lastNotice = n; snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(n.text) } }
    LaunchedEffect(Unit) { machine.materials.collect { editor.setMaterials(it.items) } }

    Box(Modifier.fillMaxSize().background(Lc.bg).windowInsetsPadding(WindowInsets.safeDrawing)) {
        Column(Modifier.fillMaxSize()) {
            TopBar(machine)
            Row(Modifier.fillMaxSize()) {
                Rail(dest) { dest = it }
                Box(Modifier.fillMaxSize()) {
                    AnimatedContent(dest, transitionSpec = { fadeIn() togetherWith fadeOut() }, label = "dest") { d ->
                        when (d) {
                            Dest.MATERIAL -> MaterialScreen(machine, editor, onNext = { dest = Dest.MOTIV })
                            Dest.MOTIV -> EditorScreen(editor, machine, onNext = { dest = Dest.START },
                                onScan = { machineTab = MachineTab.SCAN; dest = Dest.MASCHINE })
                            Dest.START -> StartScreen(machine, editor, onMaterial = { dest = Dest.MATERIAL }, onMotiv = { dest = Dest.MOTIV })
                            Dest.MASCHINE -> MaschineScreen(machine, editor, machineTab) { machineTab = it }
                            Dest.EINSTELLUNGEN -> SettingsScreen(machine)
                        }
                    }
                }
            }
        }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).padding(24.dp)) { data ->
            val error = lastNotice?.error == true
            Snackbar(
                containerColor = if (error) Color(0xFF2B1A1E) else Color(0xFF1F2A37),
                contentColor = if (error) Color(0xFFFFD0D2) else Lc.text,
                shape = RoundedCornerShape(14.dp),
            ) { Text(data.visuals.message, style = LcTypography.bodyLarge) }
        }
    }
}

@Composable
private fun TopBar(machine: MachineViewModel) {
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val host by machine.host.collectAsStateWithLifecycle()
    val readError by machine.readError.collectAsStateWithLifecycle()
    val head = headline(status, online, host, readError)
    Row(
        Modifier
            .fillMaxWidth()
            .height(68.dp)
            .background(Brush.verticalGradient(listOf(Color(0xFF0D1218), Color(0xFF0B1015))))
            .padding(start = 22.dp, end = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text("Luma", fontSize = 21.sp, fontWeight = FontWeight.Light, color = Lc.text)
            Text("Cut", fontSize = 21.sp, fontWeight = FontWeight.ExtraBold, color = Lc.accent)
        }
        Spacer(Modifier.width(6.dp))
        val connTone = when { host.isBlank() -> Tone.OFF; online == true && status?.connected == true -> Tone.OK; online == null -> Tone.BUSY; else -> Tone.BAD }
        ToneChip(if (host.isBlank()) "Nicht verbunden" else host, connTone)
        ToneChip(head.title, head.tone, Modifier.weight(1f, fill = false))
        Spacer(Modifier.weight(1f))
        status?.position?.takeIf { it.size == 3 }?.let { p ->
            // Work-area coordinates like the editor; negative = head in the laser's reserved border (parked).
            val w = de.millione.lumacut.core.Work.fromMachine(p[0], p[1])
            for ((axis, v) in listOf("X" to w.x, "Y" to w.y, "Z" to p[2])) {
                Text(axis, style = LcTypography.labelMedium, color = Lc.faint)
                Text("%.2f".format(v), style = LcTypography.titleMedium.merge(NumberStyle), color = Lc.text,
                     textAlign = TextAlign.End, modifier = Modifier.width(66.dp))
            }
        }
        Spacer(Modifier.width(4.dp))
        Box(
            Modifier
                .height(48.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(Lc.estop)
                .border(2.dp, Color(0xFFFF8A8E), RoundedCornerShape(14.dp))
                .clickable(onClickLabel = "Software-Notstopp M112") { machine.emergencyStop() }
                .padding(horizontal = 22.dp),
            contentAlignment = Alignment.Center,
        ) { Text("NOT-AUS", color = Color.White, fontWeight = FontWeight.Black, letterSpacing = 1.sp) }
    }
    Box(Modifier.fillMaxWidth().height(1.dp).background(Lc.line))
}

@Composable
private fun Rail(selected: Dest, onSelect: (Dest) -> Unit) {
    Row {
        Column(
            Modifier.width(96.dp).fillMaxHeight().background(Color(0xFF0B1016)).padding(horizontal = 10.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (d in Dest.entries) {
                if (d == Dest.MASCHINE) Box(Modifier.fillMaxWidth().height(1.dp).background(Lc.line))
                val on = d == selected
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(if (on) Lc.accentSoft else Color.Transparent)
                        .clickable { onSelect(d) }
                        .padding(vertical = 12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(d.icon, d.label, tint = if (on) Lc.accent else Lc.muted, modifier = Modifier.size(26.dp))
                    Spacer(Modifier.height(6.dp))
                    Text(d.step?.let { "$it · ${d.label}" } ?: d.label, style = LcTypography.labelMedium, color = if (on) Lc.accent else Lc.muted, textAlign = TextAlign.Center, maxLines = 1)
                }
            }
        }
        Box(Modifier.width(1.dp).fillMaxHeight().background(Lc.line))
    }
}
