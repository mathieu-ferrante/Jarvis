package fr.mathieu.jarvis

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.service.quicksettings.TileService

/** TEL-03 : tuile des réglages rapides. Un appui ouvre Jarvis prêt à écouter. */
class TuileParler : TileService() {
    override fun onClick() {
        super.onClick()
        val intention = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra(MainActivity.EXTRA_PARLER, true)
        if (android.os.Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(android.app.PendingIntent.getActivity(this, 1, intention, android.app.PendingIntent.FLAG_IMMUTABLE))
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intention)
        }
    }
}

/** Relance la connexion au démarrage du téléphone (le micro, lui, exige d'ouvrir l'appli : règle Android). */
class Demarrage : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && Reglages(context).jeton != null) {
            JarvisService.demarrer(context, sansMicro = true) // Android interdit le micro en arrière-plan au démarrage
        }
    }
}
