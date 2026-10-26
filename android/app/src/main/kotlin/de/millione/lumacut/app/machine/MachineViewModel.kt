package de.millione.lumacut.app.machine

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.core.Bed
import de.millione.lumacut.core.JobFile
import de.millione.lumacut.core.MachineStatus
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Toolpath
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class Notice(val text: String, val error: Boolean = false)

/** Selected job with its parsed toolpath and the probe point for one-click runs. */
data class JobView(val name: String, val toolpath: Toolpath?, val probe: Pt?, val probeChosen: Boolean, val error: String? = null)

class MachineViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("lumacut", Context.MODE_PRIVATE)

    private val _host = MutableStateFlow(prefs.getString("host", "") ?: "")
    val host: StateFlow<String> = _host.asStateFlow()

    private val _status = MutableStateFlow<MachineStatus?>(null)
    val status: StateFlow<MachineStatus?> = _status.asStateFlow()

    /** null = never asked, true/false = last poll answered. */
    private val _online = MutableStateFlow<Boolean?>(null)
    val online: StateFlow<Boolean?> = _online.asStateFlow()

    private val _busy = MutableStateFlow<Set<String>>(emptySet())
    val busy: StateFlow<Set<String>> = _busy.asStateFlow()

    private val _jobs = MutableStateFlow<List<JobFile>>(emptyList())
    val jobs: StateFlow<List<JobFile>> = _jobs.asStateFlow()

    private val _job = MutableStateFlow<JobView?>(null)
    val job: StateFlow<JobView?> = _job.asStateFlow()

    /** View preference: where X0/Y0 appears on screen. Machine coordinates never change. */
    private val _originBottom = MutableStateFlow(prefs.getBoolean("originBottom", false))
    val originBottom: StateFlow<Boolean> = _originBottom.asStateFlow()

    private val _notices = MutableSharedFlow<Notice>(extraBufferCapacity = 8)
    val notices: SharedFlow<Notice> = _notices

    private var client: PiClient? = null
    private var poller: Job? = null
    private var lastJobError = ""

    init { connect(_host.value, quiet = true) }

    fun notify(text: String, error: Boolean = false) { _notices.tryEmit(Notice(text, error)) }

    fun connect(ip: String, quiet: Boolean = false) {
        val trimmed = ip.trim()
        if (trimmed.isEmpty()) return
        val c = runCatching { PiClient(trimmed) }.getOrElse { if (!quiet) notify(it.message ?: "Ungültige Adresse", true); return }
        client = c
        _host.value = trimmed
        prefs.edit().putString("host", trimmed).apply()
        poller?.cancel()
        poller = viewModelScope.launch {
            while (isActive) {
                poll()
                delay(1000)
            }
        }
        refreshJobs()
    }

    fun setOriginBottom(bottom: Boolean) {
        _originBottom.value = bottom
        prefs.edit().putBoolean("originBottom", bottom).apply()
    }

    private suspend fun poll() {
        val c = client ?: return
        try {
            val s = c.status()
            _status.value = s
            _online.value = true
            if (s.job.state == "error" && s.job.error.isNotBlank() && s.job.error != lastJobError) {
                lastJobError = s.job.error
                notify("Auftrag abgebrochen: ${s.job.error}", true)
            }
        } catch (e: Exception) {
            _online.value = false
        }
    }

    /** Runs [block] against the Pi with a busy flag for [key] and a notice for the result. */
    fun request(key: String, success: String? = null, quietSuccess: Boolean = false, block: suspend (PiClient) -> String) {
        val c = client ?: run { notify("Erst die Pi-Adresse unter Einstellungen eintragen", true); return }
        if (key in _busy.value) return
        _busy.update { it + key }
        viewModelScope.launch {
            try {
                val msg = block(c)
                if (!quietSuccess) notify(success ?: msg)
            } catch (e: Exception) {
                notify(e.message ?: "Fehler", true)
            } finally {
                _busy.update { it - key }
                poll()
            }
        }
    }

    fun action(op: String, fields: Map<String, String> = emptyMap(), key: String = op, success: String? = null, quiet: Boolean = false) =
        request(key, success, quiet) { it.action(op, fields) }

    /** No confirmation and no busy lock: an emergency stop must go out immediately. */
    fun emergencyStop() {
        val c = client ?: run { notify("Nicht verbunden – physischen Not-Aus benutzen!", true); return }
        viewModelScope.launch {
            try { c.action("estop"); notify("M112 ausgelöst. SKR zurücksetzen, dann quittieren.", true) }
            catch (e: Exception) { notify("Notstopp NICHT übertragen (${e.message}) – physischen Not-Aus benutzen!", true) }
            poll()
        }
    }

    fun jog(axis: Char, distance: Double) =
        action("jog", mapOf("axis" to axis.toString(), "distance" to distance.toString()), key = "jog", quiet = true)

    fun refreshJobs() {
        val c = client ?: return
        viewModelScope.launch {
            runCatching { c.jobs() }.onSuccess { list -> _jobs.value = list.sortedByDescending { it.modified } }
        }
    }

    fun selectJob(name: String) {
        val c = client ?: return
        _job.value = JobView(name, null, null, false)
        viewModelScope.launch {
            try {
                val text = c.jobContent(name)
                val tp = withContext(Dispatchers.Default) { Toolpath.parse(text) }
                val probe = tp.bounds?.center?.let { Pt(it.x.coerceIn(Bed.SAFE, Bed.WIDTH), it.y.coerceIn(Bed.SAFE, Bed.HEIGHT)) }
                if (_job.value?.name == name) _job.value = JobView(name, tp, probe, false)
            } catch (e: Exception) {
                if (_job.value?.name == name) _job.value = JobView(name, null, null, false, e.message)
            }
        }
    }

    fun clearJob() { _job.value = null }

    fun setProbe(p: Pt) {
        if (!Bed.inWorkArea(p.x, p.y)) { notify("Abtastpunkt muss außerhalb der 30-mm-Safezone liegen", true); return }
        _job.update { it?.copy(probe = Pt(Math.round(p.x * 10) / 10.0, Math.round(p.y * 10) / 10.0), probeChosen = true) }
    }

    fun startJob(oneClick: Boolean) {
        val view = _job.value ?: return
        val fields = mutableMapOf("name" to view.name)
        if (oneClick) view.probe?.let { fields["x"] = "%.2f".format(java.util.Locale.ROOT, it.x); fields["y"] = "%.2f".format(java.util.Locale.ROOT, it.y) }
        action(if (oneClick) "autorun" else "start", fields, key = "start")
    }

    fun deleteJob(name: String) = request("delete") { c ->
        val msg = c.deleteJob(name)
        if (_job.value?.name == name) _job.value = null
        _jobs.value = c.jobs().sortedByDescending { it.modified }
        msg
    }

    fun uploadJob(name: String, gcode: String, select: Boolean = true) = request("upload") { c ->
        val fileName = PiClient.checkJobName(name)
        val msg = c.uploadJob(fileName, gcode)
        _jobs.value = c.jobs().sortedByDescending { it.modified }
        if (select) withContext(Dispatchers.Main) { selectJob(fileName) }
        msg
    }

    fun uploadFirmware(name: String, bytes: ByteArray) = request("firmware") { it.uploadFirmware(name, bytes) }

    /** Laser-off outline of the burned points ([Frame.cutPoints] or document geometry). */
    fun frame(points: List<Pt>, mode: de.millione.lumacut.core.Frame.Mode) {
        if (points.isEmpty()) { notify("Kein Motiv für den Rahmen", true); return }
        request("frame") { it.frame(de.millione.lumacut.core.Frame.program(points, mode), mode) }
    }

    fun saveSettings(values: Map<String, String>) = request("settings") { it.settings(values) }

    /** Head position the Pi would need for probing at [p] (probe tip lands on p). */
    fun probeHeadPosition(p: Pt): Pt? = _status.value?.probeOffset?.let { Pt(p.x - it.x, p.y - it.y) }
}
