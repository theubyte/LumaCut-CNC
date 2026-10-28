package de.millione.lumacut.app.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorScreen
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.Notice
import de.millione.lumacut.app.machine.headline

/** The main path is 1 Material → 2 Motiv → 3 Starten; everything else lives under Maschine. */
enum class Dest(val label: String, val icon: ImageVector, val key: String, val step: Int? = null) {
    MATERIAL("Material", LcIcons.material, "material", 1),
    MOTIV("Motiv", LcIcons.editor, "motiv", 2),
    START("Starten", LcIcons.play, "start", 3),
    MASCHINE("Maschine", LcIcons.machine, "maschine"),
    EINSTELLUNGEN("Einstellungen", LcIcons.settings, "einstellungen"),
}

@Composable
fun LumaCutApp(machine: MachineViewModel, editor: EditorViewModel) {
    var dest by rememberSaveable { mutableStateOf(if (editor.materialKey.value == null) Dest.MATERIAL else Dest.MOTIV) }
    var machineTab by rememberSaveable { mutableStateOf(MachineTab.STEUERUNG) }
    // The menu rail folds away for more work area; the button in the top bar brings it back.
    // Upright tablets start with the rail folded: the width goes to the editor's bar and canvas.
    val wideScreen = LocalConfiguration.current.screenWidthDp >= 900
    var railOpen by rememberSaveable { mutableStateOf(wideScreen) }
    val snackbar = remember { SnackbarHostState() }
    var lastNotice by remember { mutableStateOf<Notice?>(null) }
    LaunchedEffect(Unit) {
        machine.notices.collect { n -> lastNotice = n; snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(n.text) }
    }
    LaunchedEffect(Unit) { editor.notices.collect { n -> lastNotice = n; snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(n.text) } }
    LaunchedEffect(Unit) { machine.materials.collect { editor.setMaterials(it.items) } }
    LaunchedEffect(Unit) { machine.status.collect { editor.setMotion(it?.config?.motion?.toMotion() ?: de.millione.lumacut.core.MarlinWriter.Motion.FIRMWARE) } }
    // The Pi is the centre: material, areas, project, scan and settings are the same on every device.
    val workspace: de.millione.lumacut.app.workspace.WorkspaceViewModel = androidx.lifecycle.viewmodel.compose.viewModel()
    val sync: de.millione.lumacut.app.sync.PiSyncViewModel = androidx.lifecycle.viewmodel.compose.viewModel()
    LaunchedEffect(Unit) { sync.start(machine, editor, workspace) }
    val syncConflict by sync.conflict.collectAsStateWithLifecycle()
    val homeConfirm by machine.homeConfirm.collectAsStateWithLifecycle()
    val compact = isCompact()

    val host by machine.host.collectAsStateWithLifecycle()
    val content: @Composable () -> Unit = { Column(Modifier.fillMaxSize()) {
        // First start: nothing works without the laser's address, so every page says where to set it.
        if (host.isBlank() && dest != Dest.EINSTELLUNGEN) ConnectHint(Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp)) { dest = Dest.EINSTELLUNGEN }
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
    } }

    Box(Modifier.fillMaxSize().background(Lc.bg).windowInsetsPadding(WindowInsets.safeDrawing)) {
        if (compact) Column(Modifier.fillMaxSize()) {
            TopBar(machine, compact = true, railOpen = false, onToggleRail = null)
            Box(Modifier.weight(1f).fillMaxWidth()) { content() }
            BottomNav(dest) { dest = it }
        } else Row(Modifier.fillMaxSize()) {
            AnimatedVisibility(railOpen, enter = expandHorizontally(), exit = shrinkHorizontally()) { Rail(dest) { dest = it } }
            Column(Modifier.fillMaxSize()) {
                TopBar(machine, compact = false, railOpen = railOpen) { railOpen = !railOpen }
                Box(Modifier.fillMaxSize()) { content() }
            }
        }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).padding(start = 16.dp, end = 16.dp, bottom = if (compact) 92.dp else 24.dp)) { data ->
            val error = lastNotice?.error == true
            Snackbar(
                containerColor = if (error) Lc.bad else Lc.ink,
                contentColor = if (error) Color.White else Lc.onInk,
                shape = RoundedCornerShape(18.dp),
            ) { Text(data.visuals.message, style = LcTypography.bodyLarge) }
        }
    }
    if (syncConflict) AlertDialog(
        onDismissRequest = {}, containerColor = Lc.surface, shape = RoundedCornerShape(28.dp),
        title = { Text("Projekt an einem anderen Gerät geändert", style = LcTypography.titleLarge, color = Lc.text) },
        text = { Text("Auf dem Pi liegt eine neuere Fassung des Projekts, und auch hier wurde geändert. Welche soll gelten? " +
            "Die andere lässt sich mit Rückgängig bzw. am anderen Gerät wiederherstellen.", style = LcTypography.bodyLarge, color = Lc.muted) },
        confirmButton = { LcButton("Vom Pi übernehmen", { sync.resolveConflict(true) }, kind = BtnKind.PRIMARY) },
        dismissButton = { LcButton("Diese Fassung behalten", { sync.resolveConflict(false) }, kind = BtnKind.GHOST) },
    )
    if (homeConfirm) AlertDialog(
        onDismissRequest = { machine.answerHomeConfirm(false) }, containerColor = Lc.surface, shape = RoundedCornerShape(28.dp),
        title = { Text("Steht der Kopf frei?", style = LcTypography.titleLarge, color = Lc.text) },
        text = { Text("Der Pi kennt die Kopfhöhe nicht (nach Not-Aus, Stromausfall oder Neustart des Controllers). Beim Referenzieren " +
            "fährt der Kopf quer über das Bett in die Ecke. Steht die Tasterspitze über allem, was auf dem Bett liegt?", style = LcTypography.bodyLarge, color = Lc.muted) },
        confirmButton = { LcButton("Ja, referenzieren", { machine.answerHomeConfirm(true) }, kind = BtnKind.PRIMARY) },
        dismissButton = { LcButton("Abbrechen", { machine.answerHomeConfirm(false) }, kind = BtnKind.GHOST) },
    )
}

/** Brand mark: the laser icon in an accent circle. */
@Composable
private fun LogoMark(size: Dp = 40.dp) {
    Box(Modifier.size(size).clip(CircleShape).background(Lc.accent), contentAlignment = Alignment.Center) {
        Icon(LcIcons.laser, "LumaCut", tint = Lc.accentInk, modifier = Modifier.size(size * .55f))
    }
}

/**
 * One slim line (48 dp): logo icon, one status chip (connection + state), head position in small monospace, NOT-AUS.
 * Before it was 64 dp with word mark, two chips and a large position pill – space the editor and the scan need.
 */
@Composable
private fun TopBar(machine: MachineViewModel, compact: Boolean, railOpen: Boolean, onToggleRail: (() -> Unit)?) {
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val host by machine.host.collectAsStateWithLifecycle()
    val readError by machine.readError.collectAsStateWithLifecycle()
    val head = headline(status, online, host, readError)
    val width = LocalConfiguration.current.screenWidthDp
    Row(
        Modifier.fillMaxWidth().height(48.dp).padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (onToggleRail != null) Box(
            Modifier.size(40.dp).clip(CircleShape).clickable(onClickLabel = if (railOpen) "Menü einklappen" else "Menü ausklappen") { onToggleRail() },
            contentAlignment = Alignment.Center,
        ) { Icon(LcIcons.menu, if (railOpen) "Menü einklappen" else "Menü ausklappen", tint = Lc.text, modifier = Modifier.size(20.dp)) }
        if (compact || !railOpen) LogoMark(30.dp)
        val connTone = when { host.isBlank() -> Tone.OFF; online == true && status?.connected == true -> Tone.OK; online == null -> Tone.BUSY; else -> Tone.BAD }
        // Connection and state as one dot + short text; the address only while connected and there is room.
        val tone = if (connTone == Tone.OK) head.tone else connTone
        val text = if (!compact && width >= 900 && host.isNotBlank() && connTone == Tone.OK) "${head.title} · $host" else head.title
        // Takes the free width, so position and NOT-AUS sit flush right.
        StatusDot(text, tone, Modifier.weight(1f))
        if (width >= 760) status?.position?.takeIf { it.size == 3 }?.let { p ->
            // Work-area coordinates like the editor; negative = head in the laser's reserved border (parked).
            val w = de.millione.lumacut.core.Work.fromMachine(p[0], p[1])
            val mono = LcTypography.labelMedium.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace, fontWeight = FontWeight.Medium)
            Text(
                androidx.compose.ui.text.buildAnnotatedString {
                    for ((axis, v) in listOf("X" to w.x, "Y" to w.y, "Z" to p[2])) {
                        pushStyle(androidx.compose.ui.text.SpanStyle(color = Lc.accent)); append(axis); pop()
                        append(" %7.2f  ".format(v))
                    }
                }, style = mono, color = Lc.text, maxLines = 1,
            )
        }
        // Always visible and easy to hit on every screen size: the software emergency stop (48 dp high).
        Box(
            Modifier
                .height(48.dp)
                .padding(vertical = 4.dp)
                .clip(CircleShape)
                .background(Lc.estop)
                .border(2.dp, Color(0xFFFF8A8E), CircleShape)
                .clickable(onClickLabel = "Software-Notstopp M112") { machine.emergencyStop() }
                .padding(horizontal = if (compact) 16.dp else 20.dp),
            contentAlignment = Alignment.Center,
        ) { Text("NOT-AUS", color = Color.White, fontWeight = FontWeight.Black, fontSize = 15.sp, letterSpacing = 1.sp, maxLines = 1) }
    }
}

/** Small status: coloured dot and a short text, no frame (pulses while busy). */
@Composable
private fun StatusDot(text: String, tone: Tone, modifier: Modifier = Modifier) {
    val pulse = androidx.compose.animation.core.rememberInfiniteTransition(label = "dot")
    val a by pulse.animateFloat(1f, .25f, androidx.compose.animation.core.infiniteRepeatable(androidx.compose.animation.core.tween(700),
        androidx.compose.animation.core.RepeatMode.Reverse), label = "a")
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).graphicsLayer { alpha = if (tone == Tone.BUSY) a else 1f }.clip(CircleShape).background(tone.color))
        Spacer(Modifier.width(7.dp))
        Text(text, style = LcTypography.labelLarge, color = if (tone == Tone.OK || tone == Tone.OFF || tone == Tone.BUSY) Lc.text else tone.color,
             maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Tablet navigation (ref.: round icon buttons with a caption underneath). */
@Composable
private fun Rail(selected: Dest, onSelect: (Dest) -> Unit) {
    BoxWithConstraints(Modifier.width(96.dp).fillMaxHeight()) {
        val short = maxHeight < 560.dp
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(vertical = if (short) 8.dp else 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(if (short) 4.dp else 12.dp),
        ) {
            if (!short) { LogoMark(44.dp); Spacer(Modifier.height(10.dp)) }
            for (d in Dest.entries) {
                if (d == Dest.MASCHINE) Box(Modifier.width(40.dp).height(1.dp).background(Lc.line2))
                NavItem(d, d == selected, if (short) 42.dp else 52.dp) { onSelect(d) }
            }
        }
    }
}

@Composable
private fun NavItem(d: Dest, on: Boolean, circle: Dp, onClick: () -> Unit) {
    Column(
        Modifier.width(88.dp).clip(RoundedCornerShape(18.dp)).clickable(onClickLabel = d.label, onClick = onClick)
            .testTag("nav-${d.key}").padding(vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.size(circle + 6.dp)) {
            Box(
                Modifier.align(Alignment.Center).size(circle).lift(CircleShape, if (on) 10.dp else 4.dp).clip(CircleShape)
                    .background(if (on) Lc.accent else Lc.surface),
                contentAlignment = Alignment.Center,
            ) { Icon(d.icon, null, tint = if (on) Lc.accentInk else Lc.muted, modifier = Modifier.size(circle * .46f)) }
            d.step?.let {
                Box(
                    Modifier.align(Alignment.TopEnd).size(18.dp).clip(CircleShape).background(if (on) Lc.ink else Lc.surface3),
                    contentAlignment = Alignment.Center,
                ) { Text("$it", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = if (on) Lc.onInk else Lc.muted) }
            }
        }
        Spacer(Modifier.height(4.dp))
        Text(d.label, style = LcTypography.labelMedium, color = if (on) Lc.text else Lc.muted, textAlign = TextAlign.Center,
             maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = if (on) FontWeight.Bold else FontWeight.SemiBold)
    }
}

/** Phone navigation: the same five places as a bottom bar. */
@Composable
private fun BottomNav(selected: Dest, onSelect: (Dest) -> Unit) {
    Row(
        Modifier.fillMaxWidth().height(76.dp).background(Lc.surface).padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        for (d in Dest.entries) {
            val on = d == selected
            Column(
                Modifier.weight(1f).fillMaxHeight().clickable(onClickLabel = d.label) { onSelect(d) }.testTag("nav-${d.key}"),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
            ) {
                Box(
                    Modifier.size(width = 56.dp, height = 32.dp).clip(CircleShape).background(if (on) Lc.accent else Color.Transparent),
                    contentAlignment = Alignment.Center,
                ) { Icon(d.icon, null, tint = if (on) Lc.accentInk else Lc.muted, modifier = Modifier.size(21.dp)) }
                Spacer(Modifier.height(4.dp))
                Text(d.label, fontSize = 11.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Medium,
                     color = if (on) Lc.text else Lc.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun ConnectHint(modifier: Modifier = Modifier, onConnect: () -> Unit) {
    val shape = RoundedCornerShape(20.dp)
    Row(
        modifier.fillMaxWidth().clip(shape).background(Lc.accentSoft).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(LcIcons.laser, null, tint = Lc.accent, modifier = Modifier.size(22.dp))
        Text("Noch kein Laser verbunden. Erst verbinden, dann Material wählen.", style = LcTypography.bodyMedium, color = Lc.text, modifier = Modifier.weight(1f))
        LcButton("Laser verbinden", onConnect, kind = BtnKind.PRIMARY)
    }
}
