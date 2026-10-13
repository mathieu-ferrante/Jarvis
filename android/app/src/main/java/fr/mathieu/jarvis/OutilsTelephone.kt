package fr.mathieu.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.location.Location
import android.location.LocationManager
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * Outils que le téléphone expose au cerveau (MULTI-04, MAC-05 côté Android) : ils apparaissent
 * dans le registre du PC sous la forme `<appareil>_<outil>`, avec leur niveau de permission.
 */
class OutilsTelephone(private val context: Context, private val reglages: Reglages) {

    fun definitions(): JSONArray = JSONArray().apply {
        put(def("sonner", "Fait sonner le téléphone fort pendant 15 secondes, pour le retrouver.", "lecture"))
        put(def("batterie", "Donne le niveau de batterie du téléphone et s'il charge.", "lecture"))
        put(def("lampe", "Allume ou éteint la lampe torche du téléphone.", "reversible",
            JSONObject().put("type", "object").put("properties", JSONObject().put("allumer", JSONObject().put("type", "boolean")))))
        put(def("ouvrir_lien", "Propose d'ouvrir un lien sur le téléphone (notification à toucher).", "reversible",
            JSONObject().put("type", "object").put("properties", JSONObject().put("url", JSONObject().put("type", "string")))
                .put("required", JSONArray().put("url"))))
        if (reglages.positionAutorisee) {
            put(def("position", "Position approximative du téléphone (si Mathieu l'a autorisé).", "lecture"))
        }
    }

    private fun def(nom: String, description: String, niveau: String, parametres: JSONObject? = null) =
        JSONObject().put("nom", nom).put("description", description).put("niveau", niveau)
            .put("parametres", parametres ?: JSONObject().put("type", "object").put("properties", JSONObject()))

    /** Exécute un outil ; renvoie (ok, message). */
    fun executer(outil: String, args: JSONObject, notifier: (String, String, Intent?) -> Unit): Pair<Boolean, String> =
        when (outil) {
            "sonner" -> sonner()
            "batterie" -> batterie()
            "lampe" -> lampe(args.optBoolean("allumer", true))
            "ouvrir_lien" -> {
                val url = args.optString("url")
                if (!url.startsWith("https://") && !url.startsWith("http://")) false to "Adresse refusée."
                else {
                    // Android interdit d'ouvrir une activité depuis l'arrière-plan : on passe par une notification.
                    notifier("Lien envoyé par Jarvis", url, Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)))
                    true to "Lien proposé sur le téléphone (notification)."
                }
            }
            "position" -> position()
            else -> false to "Outil inconnu sur le téléphone : $outil"
        }

    private fun sonner(): Pair<Boolean, String> {
        val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        val sonnerie = RingtoneManager.getRingtone(context, uri) ?: return false to "Aucune sonnerie disponible."
        sonnerie.audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build()
        sonnerie.play()
        Handler(Looper.getMainLooper()).postDelayed({ sonnerie.stop() }, 15_000)
        return true to "Le téléphone sonne."
    }

    private fun batterie(): Pair<Boolean, String> {
        val bm = context.getSystemService(BatteryManager::class.java)
        val niveau = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        return true to "Batterie à $niveau %${if (bm.isCharging) ", en charge" else ""}."
    }

    private fun lampe(allumer: Boolean): Pair<Boolean, String> = runCatching {
        val cm = context.getSystemService(CameraManager::class.java)
        val id = cm.cameraIdList.firstOrNull() ?: return false to "Pas de lampe."
        cm.setTorchMode(id, allumer)
        true to if (allumer) "Lampe allumée." else "Lampe éteinte."
    }.getOrElse { false to "Lampe indisponible : ${it.message}" }

    @SuppressLint("MissingPermission")
    private fun position(): Pair<Boolean, String> {
        if (!reglages.positionAutorisee) return false to "Mathieu n'a pas autorisé le partage de position."
        val accorde = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!accorde) return false to "Permission de position non accordée."
        val lm = context.getSystemService(LocationManager::class.java)
        val loc: Location? = listOf(LocationManager.FUSED_PROVIDER, LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)
            .filter { Build.VERSION.SDK_INT >= 31 || it != LocationManager.FUSED_PROVIDER }
            .mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
            .maxByOrNull { it.time }
        loc ?: return false to "Position inconnue pour l'instant."
        // Arrondie à ~100 m : assez pour un rappel de lieu, sans précision inutile (TEL-06)
        return true to "Position : %.3f, %.3f (précision ~%d m).".format(loc.latitude, loc.longitude, loc.accuracy.toInt().coerceAtLeast(100))
    }
}
