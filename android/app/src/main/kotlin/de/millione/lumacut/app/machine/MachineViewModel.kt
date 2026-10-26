package de.millione.lumacut.app.machine

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.core.DiscoveredLaser
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.LaserDiscovery
import de.millione.lumacut.core.JobFile
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.MachineStatus
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.PiConflictException
import de.millione.lumacut.core.PiException
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Scan
import de.millione.lumacut.core.Toolpath
import de.millione.lumacut.core.Work
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
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import java.io.File
import java.net.Inet4Address

data class Notice(val text: String, val error: Boolean = false)

/** Materials of the Pi database; [fromPi] false = offline copy that cannot be changed. */
data class MaterialState(val revision: Int = 0, val items: List<Material> = emptyList(), val fromPi: Boolean = false)

/** The "Laser auswählen" popup: [found] are LumaCut Pis in the Wi-Fi subnet. */
data class DiscoveryState(val open: Boolean = false, val scanning: Boolean = false,
                          val found: List<DiscoveredLaser> = emptyList(), val note: String? = null)

/** Selected job with its parsed toolpath and the probe point (work-area mm) for one-click runs. */
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

    /** Set when the Pi answers but its status cannot be read (version mismatch), else null. */
    private val _readError = MutableStateFlow<String?>(null)
    val readError: StateFlow<String?> = _readError.asStateFlow()

    private val _busy = MutableStateFlow<Set<String>>(emptySet())
    val busy: StateFlow<Set<String>> = _busy.asStateFlow()

    private val _jobs = MutableStateFlow<List<JobFile>>(emptyList())
    val jobs: StateFlow<List<JobFile>> = _jobs.asStateFlow()

    private val _job = MutableStateFlow<JobView?>(null)
    val job: StateFlow<JobView?> = _job.asStateFlow()

    private val _notices = MutableSharedFlow<Notice>(extraBufferCapacity = 8)
    val notices: SharedFlow<Notice> = _notices

    private var client: PiClient? = null
    private var poller: Job? = null
    private var lastJobError = ""
    private val materialFile = File(app.filesDir, "materials.json")
    private var materialsTriedAt = 0L

    private val _discovery = MutableStateFlow(DiscoveryState())
    val discovery: StateFlow<DiscoveryState> = _discovery.asStateFlow()
    private var scanJob: Job? = null
    private val pollLock = Mutex()
    private var failures = 0
    private var calmNoticeShown = false

    private val _materials = MutableStateFlow(MaterialState(0, loadCachedMaterials()))
    val materials: StateFlow<MaterialState> = _materials.asStateFlow()

    // The saved address is simply used; nothing is searched or switched automatically.
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
                delay(1500)
            }
        }
        refreshJobs()
    }

    /** The Pi client, or null with a notice when no address is set. */
    fun clientOrNotify(): PiClient? = client ?: run { notify("Erst die Pi-Adresse unter Einstellungen eintragen", true); null }

    /** Fresh status right now (scan and probe runs wait on it). */
    suspend fun refreshStatus(): MachineStatus? { poll(wait = true); return _status.value }

    /** One status request at a time: [wait] = wait for a running one (fresh data needed), otherwise skip when one is running. */
    private suspend fun poll(wait: Boolean = false) {
        if (wait) pollLock.lock() else if (!pollLock.tryLock()) return
        try { pollOnce() } finally { pollLock.unlock() }
    }

    private suspend fun pollOnce() {
        val c = client ?: return
        try {
            val s = c.status()
            if (c !== client) return          // the address was changed while the request ran
            _status.value = s
            _online.value = true
            _readError.value = null
            failures = 0; calmNoticeShown = false
            if (!_materials.value.fromPi && System.currentTimeMillis() - materialsTriedAt > 15_000) refreshMaterials()
            if (s.job.state == "error" && s.job.error.isNotBlank() && s.job.error != lastJobError) {
                lastJobError = s.job.error
                notify("Auftrag abgebrochen: ${s.job.error}", true)
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            if (e is de.millione.lumacut.core.PiStatusFormatException) _readError.value = e.message
            // Offline only after 3 failed requests in a row (about 5 s); a running job is never touched by this.
            failures++
            if (failures >= 3) {
                _online.value = false
                if (_status.value?.job?.active == true && !calmNoticeShown) {
                    calmNoticeShown = true
                    notify("Verbindung zum Pi kurz weg – der Auftrag läuft auf dem Pi weiter.")
                }
            }
        }
    }

    /* ---------- find the laser in the Wi-Fi ---------- */

    fun scanNetwork() {
        scanJob?.cancel()
        _discovery.update { it.copy(open = true, scanning = true, note = null) }
        scanJob = viewModelScope.launch {
            val ip = withContext(Dispatchers.IO) { localIpv4() }
            if (ip == null) {
                _discovery.update { it.copy(scanning = false, found = emptyList(), note = "Das Tablet ist mit keinem WLAN verbunden – WLAN einschalten oder die Adresse von Hand eintragen.") }
                return@launch
            }
            val found = try { LaserDiscovery.scan(ip) } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { emptyList() }
            _discovery.update {
                it.copy(scanning = false, found = found,
                    note = if (found.isEmpty()) "Kein Laser gefunden. Ist er eingeschaltet und im selben WLAN? Dann erneut suchen oder die Adresse eintragen." else null)
            }
        }
    }

    fun dismissDiscovery() { scanJob?.cancel(); _discovery.value = DiscoveryState() }

    fun chooseLaser(l: DiscoveredLaser) { dismissDiscovery(); connect(l.host) }

    /** IPv4 address of the active Wi-Fi/LAN connection (private ranges only), or null. */
    private fun localIpv4(): String? {
        val cm = getApplication<Application>().getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return null
        val net = cm.activeNetwork ?: return null
        val props = cm.getLinkProperties(net) ?: return null
        return props.linkAddresses.map { it.address }.filterIsInstance<Inet4Address>()
            .mapNotNull { it.hostAddress }.firstOrNull { PiClient.isLocalIpv4(it) }
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
                // Toolpath is in machine mm; the probe point lives in the work area like everything the user sees.
                val probe = tp.bounds?.center?.let { Work.fromMachine(it).let { w -> Pt(w.x.coerceIn(0.0, Work.WIDTH), w.y.coerceIn(0.0, Work.HEIGHT)) } }
                if (_job.value?.name == name) _job.value = JobView(name, tp, probe, false)
            } catch (e: Exception) {
                if (_job.value?.name == name) _job.value = JobView(name, null, null, false, e.message)
            }
        }
    }

    fun clearJob() { _job.value = null }

    fun setProbe(p: Pt) {
        if (!Work.contains(p)) { notify("Abtastpunkt muss im Arbeitsbereich liegen", true); return }
        _job.update { it?.copy(probe = Pt(Math.round(p.x * 10) / 10.0, Math.round(p.y * 10) / 10.0), probeChosen = true) }
    }

    fun startJob(oneClick: Boolean) {
        val view = _job.value ?: return
        val fields = mutableMapOf("name" to view.name)
        if (oneClick) view.probe?.let { Work.toMachine(it) }?.let { fields["x"] = "%.2f".format(java.util.Locale.ROOT, it.x); fields["y"] = "%.2f".format(java.util.Locale.ROOT, it.y) }
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

    /* ---------- material database on the Pi (offline: last copy, read only) ---------- */

    private fun loadCachedMaterials(): List<Material> = runCatching {
        Document.JSON.decodeFromString(ListSerializer(Material.serializer()), materialFile.readText())
    }.getOrNull()?.takeIf { it.isNotEmpty() } ?: Material.defaults()

    private suspend fun loadMaterials(c: PiClient) {
        val list = c.materials()
        val items = list.materials.map { it.toMaterial() }
        _materials.value = MaterialState(list.revision, items, fromPi = true)
        withContext(Dispatchers.IO) {
            runCatching { materialFile.writeText(Document.JSON.encodeToString(ListSerializer(Material.serializer()), items)) }
        }
    }

    fun refreshMaterials() {
        val c = client ?: return
        materialsTriedAt = System.currentTimeMillis()
        viewModelScope.launch {
            try { loadMaterials(c) }
            catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (e: Exception) { /* offline: the cached list stays */ }
        }
    }

    /** Creates or updates [m] on the Pi; a stale revision (409) reloads the list and asks to save again. */
    fun saveMaterial(m: Material, isNew: Boolean) {
        if (!_materials.value.fromPi) { notify("Materialien ändern geht nur mit Verbindung zum Pi", true); return }
        request("material", "„${m.name}“ gespeichert") { c ->
            try {
                if (isNew) c.createMaterial(m, _materials.value.revision) else c.updateMaterial(m, _materials.value.revision)
            } catch (e: PiConflictException) {
                loadMaterials(c)
                throw PiException("Die Liste wurde inzwischen geändert und neu geladen – bitte noch einmal speichern.")
            }
            loadMaterials(c)
            "gespeichert"
        }
    }

    fun deleteMaterial(id: String) {
        if (!_materials.value.fromPi) { notify("Materialien ändern geht nur mit Verbindung zum Pi", true); return }
        request("material", "Material gelöscht") { c ->
            try {
                c.deleteMaterial(id, _materials.value.revision)
            } catch (e: PiConflictException) {
                loadMaterials(c)
                throw PiException("Die Liste wurde inzwischen geändert und neu geladen – bitte noch einmal löschen.")
            }
            loadMaterials(c)
            "gelöscht"
        }
    }

    /* ---------- main path: frame and start ---------- */

    /** Uploads the built job and starts the Pi's automatic run: home if needed, probe, height correction, laser, park. */
    fun startAutomatic(name: String, gcode: String) = request("start", quietSuccess = true) { c ->
        val fileName = PiClient.checkJobName(name)
        c.uploadJob(fileName, gcode)
        _jobs.value = c.jobs().sortedByDescending { it.modified }
        c.autorun(fileName)
    }

    /** Laser-off outline of the motif; references the machine first when that has not happened yet. */
    fun frameAutomatic(points: List<Pt>) {
        if (points.isEmpty()) { notify("Nichts zu zeigen – erst ein Motiv anlegen", true); return }
        request("frame", quietSuccess = true) { c ->
            if (_status.value?.homed != true) c.action("home")
            val mode = de.millione.lumacut.core.Frame.Mode.BOX
            c.frame(de.millione.lumacut.core.Frame.program(points, mode), mode)
        }
    }

    /** False when the switch cannot reach work point [p] (head would leave X30..390/Y30..370); null without offset. */
    fun probeReachable(p: Pt): Boolean? = _status.value?.probeOffset?.let { Scan.reachable(p, it) }
}
