package de.millione.lumacut.app

import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.github.takahirom.roborazzi.captureRoboImage
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.core.MachineStatus
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.ShapeLib
import de.millione.lumacut.core.grouped
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Renders every main screen as a PNG (build/screenshots) on tablet and phone, light and dark.
 * The machine is faked as connected and homed (no network); the motif is a heart and a star.
 */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34])
class ScreenshotTest {
    @get:Rule val rule = createAndroidComposeRule<MainActivity>()

    @Test @Config(qualifiers = "w1280dp-h800dp-land-mdpi") fun tablet() = tour("tablet")
    @Test @Config(qualifiers = "w1280dp-h800dp-land-night-mdpi") fun tabletDark() = tour("tablet-dunkel")
    @Test @Config(qualifiers = "w411dp-h891dp-port-night-xhdpi") fun phoneDark() = tour("handy-dunkel")
    // The owner's Galaxy Tab S7 FE: 2560 × 1600 px at density ~2.1 minus status and task bar, larger system font.
    @Test @Config(qualifiers = "w1200dp-h720dp-land-xhdpi", fontScale = 1.1f) fun tabS7fe() = tour("tab-s7fe")
    @Test @Config(qualifiers = "w752dp-h1160dp-port-xhdpi", fontScale = 1.1f) fun tabS7feHoch() = tour("tab-s7fe-hoch")
    @Test @Config(qualifiers = "w411dp-h891dp-port-xhdpi") fun phone() = tour("handy")
    @Test @Config(qualifiers = "w891dp-h411dp-land-xhdpi") fun phoneLandscape() = tour("handy-quer")

    private fun shot(name: String) {
        rule.waitForIdle()
        // Background work (toolpath build on Dispatchers.Default) and the snackbar's 4 s should be over.
        Thread.sleep(1500)
        rule.mainClock.advanceTimeBy(6000)
        rule.waitForIdle()
        rule.onRoot().captureRoboImage("build/screenshots/$name.png")
    }

    /** Navigates by the test tag nav-<key> (new shell) or the first matching label (old shell). */
    private fun go(key: String, vararg labels: String) {
        val tagged = rule.onAllNodes(hasTestTag("nav-$key"))
        if (tagged.fetchSemanticsNodes().isNotEmpty()) { tagged.onFirst().performClick(); rule.waitForIdle(); return }
        for (l in labels) {
            val n = rule.onAllNodesWithText(l)
            if (n.fetchSemanticsNodes().isNotEmpty()) { n.onFirst().performClick(); rule.waitForIdle(); return }
        }
        error("Navigation $key nicht gefunden")
    }

    private fun tab(label: String) {
        val n = rule.onAllNodesWithText(label, substring = true)
        if (n.fetchSemanticsNodes().isNotEmpty()) { n.onFirst().performClick(); rule.waitForIdle() }
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> field(vm: Any, name: String) =
        vm.javaClass.getDeclaredField(name).apply { isAccessible = true }.get(vm) as MutableStateFlow<T>

    private fun tour(prefix: String) {
        val provider = ViewModelProvider(rule.activity)
        val machine = provider[MachineViewModel::class.java]
        val editor = provider[EditorViewModel::class.java]
        shot("$prefix-0-erststart")
        rule.runOnUiThread {
            field<String>(machine, "_host").value = "192.168.2.89"
            field<Boolean?>(machine, "_online").value = true
            field<MachineStatus?>(machine, "_status").value = MachineStatus(
                connected = true, state = "Idle", homed = true, position = listOf(182.0, 160.0, 24.5),
                identity = "FIRMWARE_NAME:Marlin 2.1.2.5 (LumaCut)", lights = true, light_dimmable = true, light_brightness = 70.0,
                workpiece_surface_z = 3.0, laser_focus_z = 9.2, features = listOf("autorun_mesh", "materials", "workspace", "app_update"),
                coord_convention = PiClient.COORD_CONVENTION, recent = listOf("echo: busy processing", "X:182.00 Y:160.00 Z:24.50"),
            )
        }
        go("material", "1 · Material", "Material")
        shot("$prefix-1-material")
        rule.runOnUiThread {
            machine.materials.value.items.grouped("").firstOrNull()?.let(editor::selectMaterial)
            editor.addShape("Herz", listOf(ShapeLib.heart(80.0, 72.0)), "Schneiden")
            editor.moveSelected(-70.0, 0.0, "shot-a")
            editor.addShape("Stern", listOf(ShapeLib.star(5, 70.0, 66.0)), "Schneiden")
            editor.moveSelected(70.0, 0.0, "shot-b")
        }
        go("motiv", "2 · Motiv", "Motiv")
        shot("$prefix-2-motiv")
        // Zoomed in: the sheet must stay inside the canvas and never cover the tools.
        val zoomIn = rule.onAllNodesWithContentDescription("Vergrößern")
        if (zoomIn.fetchSemanticsNodes().isNotEmpty()) { repeat(3) { zoomIn.onFirst().performClick() }; shot("$prefix-2b-motiv-zoom") }
        go("start", "3 · Starten", "Starten")
        shot("$prefix-3-starten")
        go("maschine", "Maschine")
        shot("$prefix-4-maschine")
        tab("Kalibrieren"); shot("$prefix-5-kalibrieren")
        tab("Arbeitsplatz"); shot("$prefix-6-scan")
        tab("Aufträge"); shot("$prefix-7-auftraege")
        go("einstellungen", "Einstellungen")
        shot("$prefix-8-einstellungen")
    }
}
