package de.millione.lumacut.core

import kotlinx.serialization.Serializable

/**
 * A project saved on the Pi (/api/projects, Pi feature "projects"): the
 * shelf next to the one open project in /api/workspace/project.
 */
@Serializable
data class SavedProject(
    val id: String,
    val name: String,
    val bytes: Long = 0,
    val updated_at: String = "",
    val updated_by: String = "",
    val elements: Int = 0,
    val layers: Int = 0,
    val plates: Int = 1,
    /** Only in the answer to a save: an older project with this name was replaced. */
    val replaced: Boolean = false,
)

@Serializable
internal data class SavedProjectList(val projects: List<SavedProject> = emptyList())

@Serializable
internal data class SavedProjectReply(val project: SavedProject)

object SavedProjects {
    const val FEATURE = "projects"

    /** "29.10.2026 22:04 · Tablet · 2 Elemente" for the list; [updatedAt] is UTC as the Pi writes it. */
    fun line(p: SavedProject, zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): String {
        val time = runCatching {
            java.time.Instant.parse(p.updated_at).atZone(zone)
                .format(java.time.format.DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm"))
        }.getOrDefault("")
        return listOf(time, p.updated_by, "${p.elements} Element" + if (p.elements == 1) "" else "e")
            .filter { it.isNotBlank() }.joinToString(" · ")
    }

    /** The saved project with this name (same rule as the Pi: case does not matter). */
    fun named(list: List<SavedProject>, name: String): SavedProject? {
        val n = name.trim().split(Regex("\\s+")).joinToString(" ")
        return list.firstOrNull { it.name.equals(n, ignoreCase = true) }
    }
}
