package de.millione.lumacut.app

import android.os.Bundle
import android.view.WindowManager
import android.graphics.Color
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LumaCutApp
import de.millione.lumacut.app.ui.LumaCutTheme
import de.millione.lumacut.app.ui.ThemeMode

class MainActivity : ComponentActivity() {
    private val machine: MachineViewModel by viewModels()
    private val editor: EditorViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Lc.palette = ThemeMode.resolve(this)
        setContent {
            // Status and navigation bar icons dark on the light theme, light on the dark one.
            val dark = Lc.dark
            LaunchedEffect(dark) {
                val style = if (dark) SystemBarStyle.dark(Color.TRANSPARENT) else SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
                enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
            }
            val status by machine.status.collectAsStateWithLifecycle()
            // Keep the display on while the laser works: the operator watches it.
            LaunchedEffect(status?.job?.active) {
                if (status?.job?.active == true) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
            LumaCutTheme { LumaCutApp(machine, editor) }
        }
    }
}
