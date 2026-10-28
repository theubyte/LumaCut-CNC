package de.millione.lumacut.app.ui

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.update.AppInstaller

/** Settings card "App-Update": installed and offered version, check now, update. */
@Composable
fun UpdateCard(machine: MachineViewModel) {
    val u by machine.update.collectAsStateWithLifecycle()
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var confirm by rememberConfirm()
    val supported = "app_update" in (status?.features ?: emptyList())
    val running = status?.job?.active == true
    val offered = u.info?.takeIf { it.available }
    LcCard {
        CardTitle("App-Update")
        SmallText("Installiert: ${u.installedName} (${u.installedCode})")
        SmallText(when {
            online != true -> "Der Pi ist nicht erreichbar."
            !supported -> "Der Pi-Dienst kann noch keine App-Updates liefern – Pi-Dienst aktualisieren."
            offered == null -> "Angeboten: nichts" + (u.info?.error?.let { " ($it)" } ?: "")
            u.available -> "Update ${offered.version_name} verfügbar (${offered.size / 1024 / 1024} MB)"
            else -> "Angeboten: ${offered.version_name} – die App ist aktuell."
        })
        Spacer(Modifier.height(10.dp))
        u.progress?.let { LinearProgressIndicator(progress = { it }, Modifier.fillMaxWidth(), color = Lc.accent, trackColor = Lc.surface3); Spacer(Modifier.height(10.dp)) }
        u.error?.let { Banner(it, Lc.bad); Spacer(Modifier.height(10.dp)) }
        if (running) { Banner("Während ein Auftrag läuft, wird nicht aktualisiert.", Lc.info); Spacer(Modifier.height(10.dp)) }
        if (u.available) {
            LcButton(if (u.installing) "Installation läuft …" else "Aktualisieren", {
                if (AppInstaller.canInstall(context)) machine.startUpdate()
                else confirm = Confirm("Installation erlauben?", "Android muss dieser App einmal erlauben, Apps zu installieren. Auf der nächsten Seite „Von dieser Quelle zulassen“ einschalten und zurückgehen, dann erneut auf Aktualisieren tippen.", "Einstellung öffnen") {
                    context.startActivity(AppInstaller.permissionIntent(context))
                }
            }, Modifier.fillMaxWidth(), kind = BtnKind.PRIMARY, busy = u.progress != null || u.installing, enabled = !running && online == true)
            Spacer(Modifier.height(10.dp))
        }
        LcButton("Jetzt prüfen", { machine.checkUpdate(refresh = true, quiet = false) }, Modifier.fillMaxWidth(),
                 busy = u.checking, enabled = supported && !running && online == true)
    }
    ConfirmDialog(confirm) { confirm = null }
}
