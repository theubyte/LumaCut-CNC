package de.millione.lumacut.app.update

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.provider.Settings
import androidx.core.content.pm.PackageInfoCompat
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import java.io.File

/** Installs a downloaded APK through a PackageInstaller session; Android always asks the user to confirm. */
object AppInstaller {
    private const val ACTION = "de.millione.lumacut.INSTALL_RESULT"

    private val _failures = MutableSharedFlow<String>(extraBufferCapacity = 4)
    /** One sentence for each install that did not happen (cancelled or refused by Android). */
    val failures: SharedFlow<String> = _failures

    fun installedCode(ctx: Context): Int =
        PackageInfoCompat.getLongVersionCode(ctx.packageManager.getPackageInfo(ctx.packageName, 0)).toInt()

    fun installedName(ctx: Context): String =
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"

    fun canInstall(ctx: Context): Boolean = ctx.packageManager.canRequestPackageInstalls()

    /** System page where the user allows this app to install apps ("Unbekannte Apps installieren"). */
    fun permissionIntent(ctx: Context): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun install(ctx: Context, apk: File) {
        val installer = ctx.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply { setSize(apk.length()) }
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            apk.inputStream().use { input ->
                session.openWrite("lumacut.apk", 0, apk.length()).use { out -> input.copyTo(out); session.fsync(out) }
            }
            val intent = Intent(ctx, InstallResultReceiver::class.java).setAction(ACTION)
            val pending = PendingIntent.getBroadcast(ctx, id, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            session.commit(pending.intentSender)
        }
    }

    internal fun fail(text: String) { _failures.tryEmit(text) }
}

class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if (confirm != null) context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            PackageInstaller.STATUS_SUCCESS -> Unit
            PackageInstaller.STATUS_FAILURE_ABORTED -> AppInstaller.fail("Installation abgebrochen.")
            PackageInstaller.STATUS_FAILURE_CONFLICT, PackageInstaller.STATUS_FAILURE_INCOMPATIBLE ->
                AppInstaller.fail("Die installierte App ist mit einem anderen Schlüssel signiert – einmal deinstallieren und die neue APK installieren.")
            PackageInstaller.STATUS_FAILURE_STORAGE -> AppInstaller.fail("Nicht genug Speicherplatz für das Update.")
            else -> AppInstaller.fail("Android hat die Installation abgelehnt: " + (intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "unbekannter Fehler"))
        }
    }
}
