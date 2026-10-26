package de.millione.lumacut.app.machine

import de.millione.lumacut.app.ui.Tone
import de.millione.lumacut.core.MachineStatus

data class Headline(val tone: Tone, val title: String, val text: String)

/** One sentence that tells the operator what the machine is doing and what comes next. */
fun headline(s: MachineStatus?, online: Boolean?, host: String, readError: String? = null): Headline = when {
    host.isBlank() -> Headline(Tone.OFF, "Nicht eingerichtet", "Pi-Adresse unter Einstellungen eintragen.")
    online == null -> Headline(Tone.BUSY, "Verbinde …", host)
    online == false && readError != null -> Headline(Tone.BAD, "Pi-Antwort nicht lesbar", readError)
    online == false || s == null -> Headline(Tone.BAD, "Pi nicht erreichbar", "WLAN und Adresse $host prüfen.")
    !s.connected -> Headline(Tone.BAD, "Controller getrennt", s.fault.ifBlank { "USB-Verbindung zum SKR fehlt." })
    s.emergency_latched -> Headline(Tone.BAD, "Notstopp aktiv", "SKR zurücksetzen (Reset-Taste oder kurz stromlos), dann quittieren.")
    s.firmware_update.state in setOf("uploading", "rebooting") -> Headline(Tone.BUSY, "Firmware-Update", s.firmware_update.message)
    s.frame.active -> Headline(Tone.BUSY, "Rahmenfahrt", "Laser aus · ${s.frame.line}/${s.frame.total}")
    s.job.state == "homing" -> Headline(Tone.BUSY, "Referenzfahrt", s.job.file)
    s.job.state == "probing" -> Headline(Tone.BUSY, "Werkstück wird abgetastet", s.job.file)
    s.job.state == "running" -> Headline(Tone.BUSY, "Auftrag läuft", s.job.file)
    s.owner == "lightburn" -> Headline(Tone.WARN, "LightBurn verbunden", "Steuerung über die App erst nach Trennen von LightBurn.")
    !s.ownerFree -> Headline(Tone.BUSY, "Beschäftigt", "Belegt durch ${s.owner}")
    s.state == "Busy" -> Headline(Tone.BUSY, "In Bewegung", "")
    !s.homed -> Headline(Tone.WARN, "Bereit · nicht referenziert", "Vor dem Arbeiten referenzieren: X/Y, dann Z, dann 20 mm hoch.")
    s.workpiece_surface_z == null -> Headline(Tone.OK, "Bereit", "Referenziert. Werkstück noch nicht abgetastet.")
    else -> Headline(Tone.OK, "Bereit", "Referenziert und abgetastet. Der Fokus wird vor dem ersten Laserweg angefahren.")
}

fun MachineStatus?.canControl(online: Boolean?) =
    this != null && online == true && connected && !emergency_latched && ownerFree && !job.active && !frame.active
