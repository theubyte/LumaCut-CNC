package de.millione.lumacut.app

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.LumaCutApp
import de.millione.lumacut.app.ui.LumaCutTheme

class MainActivity : ComponentActivity() {
    private val machine: MachineViewModel by viewModels()
    private val editor: EditorViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
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
