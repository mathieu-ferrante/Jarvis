package fr.mathieu.jarvis

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Service de premier plan (exigé par Android pour rester connecté et écouter) :
 * - garde la connexion WebSocket avec le PC (TEL-04 : notifications sans Google) ;
 * - affiche notifications et demandes de confirmation ;
 * - exécute les outils du téléphone demandés par le cerveau ;
 * - fait tourner le mot de réveil si Mathieu l'a activé (TEL-02).
 */
class JarvisService : Service() {
    private lateinit var reglages: Reglages
    private var connexion: Connexion? = null
    private var reveil: Reveil? = null
    private lateinit var outils: OutilsTelephone
    private lateinit var enregistreur: Enregistreur

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        reglages = Reglages(this)
        outils = OutilsTelephone(this, reglages)
        enregistreur = Enregistreur(this, reglages)
        creerCanaux()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        sansMicro = intent?.getBooleanExtra(EXTRA_SANS_MICRO, false) == true
        val type = if (reglages.reveilActif && !sansMicro) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        else ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        ServiceCompat.startForeground(this, 1, notificationPermanente(), type)
        val jeton = reglages.jeton
        if (jeton != null && reglages.serveur.isNotEmpty() && connexion == null) {
            connexion = Connexion(reglages.serveur, jeton, ::surMessage).also { it.ouvrir() }
        }
        appliquerReveil()
        return START_STICKY
    }

    override fun onDestroy() {
        reveil?.arreter()
        connexion?.fermer()
        instance = null
        super.onDestroy()
    }

    private var sansMicro = false

    fun appliquerReveil() {
        if (reglages.reveilActif && !sansMicro && reveil == null) {
            val c = connexion ?: return
            reveil = Reveil(this, reglages, c.http, ::verifierReveil) { parlerApresReveil() }
            if (reveil?.demarrer() != true) {
                reveil = null
                Etat.ajouter("systeme", "Mot de réveil indisponible (modèles non récupérés auprès du PC).")
            }
        } else if (!reglages.reveilActif) {
            reveil?.arreter()
            reveil = null
        }
    }

    // --- Messages du PC -------------------------------------------------------------------

    private fun surMessage(m: JSONObject) {
        val d = m.optJSONObject("donnees") ?: JSONObject()
        when (m.optString("type")) {
            "bienvenue" -> {
                connexion?.envoyer(JSONObject().put("type", "outils").put("outils", outils.definitions()), false)
                Thread { memoriserDerniereVue() }.start()
            }
            "morceau" -> Etat.morceau(d.optString("texte"))
            "fin" -> Etat.finReponse()
            "notification" -> {
                val titre = d.optString("titre", "Jarvis")
                val texte = d.optString("texte")
                Etat.ajouter("systeme", "$titre — $texte")
                if (Etat.auPremierPlan) connexion?.envoyer(JSONObject().put("type", "lu").put("id", d.optString("id_notification")), false)
                else notifier(titre, texte, null, CANAL_NOTIFICATIONS)
            }
            "confirmation" -> if (d.optString("appareil") in listOf(reglages.identifiant, "pc")) {
                Etat.ajouterConfirmation(d)
                notifier("Confirmation demandée", d.optString("question"), null, CANAL_CONFIRMATIONS)
            }
            "voix_transcription" -> d.optString("texte").takeIf { it.isNotEmpty() }?.let { Etat.ajouter("moi", "🎙 $it") }
            "voix_reponse" -> d.optString("texte").takeIf { it.isNotEmpty() }?.let { Etat.ajouter("jarvis", it) }
            "executer" -> Thread {
                val (ok, message) = runCatching {
                    outils.executer(d.optString("outil"), d.optJSONObject("args") ?: JSONObject()) { t, x, i -> notifier(t, x, i, CANAL_NOTIFICATIONS) }
                }.getOrElse { false to "Erreur sur le téléphone : ${it.message}" }
                connexion?.envoyer(JSONObject().put("type", "resultat").put("donnees",
                    JSONObject().put("id", d.optString("id")).put("ok", ok).put("message", message)), false)
            }.start()
            "recevoir" -> recevoir(d)
        }
    }

    /** TEL-07 : garde les prochains rappels pour les afficher hors connexion. */
    private fun memoriserDerniereVue() {
        val c = connexion ?: return
        runCatching {
            val requete = Request.Builder().url("${reglages.serveur}/api/rappels").header("Authorization", "Bearer ${reglages.jeton}").build()
            c.http.newCall(requete).execute().use { rep ->
                val rappels = JSONObject(rep.body.string()).optJSONArray("rappels") ?: return
                reglages.derniereVue = (0 until minOf(rappels.length(), 5)).joinToString(" · ") {
                    val r = rappels.getJSONObject(it)
                    "${r.optString("quand").replace('T', ' ').take(16)} ${r.optString("texte")}"
                }.ifEmpty { "aucun rappel" }
            }
        }
    }

    private fun recevoir(d: JSONObject) {
        when (d.optString("nature")) {
            "lien" -> notifier("Lien reçu", d.optString("contenu"),
                Intent(Intent.ACTION_VIEW, android.net.Uri.parse(d.optString("contenu"))), CANAL_NOTIFICATIONS)
            "texte" -> {
                val presse = getSystemService(android.content.ClipboardManager::class.java)
                presse.setPrimaryClip(android.content.ClipData.newPlainText("Jarvis", d.optString("contenu")))
                notifier("Texte reçu (copié)", d.optString("contenu"), null, CANAL_NOTIFICATIONS)
            }
            "fichier" -> Thread { telechargerFichier(d.optString("url"), d.optString("nom")) }.start()
            "sonner" -> outils.executer("sonner", JSONObject()) { _, _, _ -> }
        }
    }

    private fun telechargerFichier(url: String, nom: String) {
        val c = connexion ?: return
        runCatching {
            val requete = Request.Builder().url(reglages.serveur + url).header("Authorization", "Bearer ${reglages.jeton}").build()
            c.http.newCall(requete).execute().use { rep ->
                check(rep.isSuccessful) { "code ${rep.code}" }
                val dossier = getExternalFilesDir(android.os.Environment.DIRECTORY_DOWNLOADS) ?: filesDir
                val f = java.io.File(dossier, nom.replace(Regex("[\\\\/:*?\"<>|]"), "_"))
                f.outputStream().use { rep.body.byteStream().copyTo(it) }
                notifier("Fichier reçu", "${f.name} (dans les fichiers de l'appli Jarvis)", null, CANAL_NOTIFICATIONS)
            }
        }.onFailure { notifier("Fichier non reçu", it.message ?: "", null, CANAL_NOTIFICATIONS) }
    }

    // --- Actions de l'interface -----------------------------------------------------------

    fun envoyerTexte(texte: String) {
        Etat.ajouter("moi", texte)
        connexion?.envoyer(JSONObject().put("type", "texte").put("texte", texte))
            ?: Etat.ajouter("systeme", "Pas de connexion : message gardé pour plus tard.")
    }

    fun confirmer(id: Int, oui: Boolean, biometrie: Boolean) {
        Etat.retirerConfirmation(id)
        connexion?.envoyer(JSONObject().put("type", "confirmer").put("id", id).put("oui", oui).put("biometrie", biometrie), false)
    }

    fun arretUrgence() = connexion?.envoyer(JSONObject().put("type", "arret"), false)

    fun commencerParole() = runCatching { enregistreur.commencer() }.onFailure { Etat.ajouter("systeme", "Micro indisponible.") }

    fun terminerParole() = enregistreur.terminer { transcription, reponse ->
        if (transcription.isNotEmpty()) Etat.ajouter("moi", "🎙 $transcription")
        Etat.ajouter("jarvis", reponse)
    }

    private fun parlerApresReveil() {
        // Après « Jarvis » : enregistrement de 5 s (la fin de parole fine est faite côté PC)
        commencerParole()
        android.os.Handler(mainLooper).postDelayed({ terminerParole() }, 5000)
    }

    /** Second étage du mot de réveil : le PC transcrit 1,6 s et dit si « Jarvis » y figure. */
    private fun verifierReveil(pcm: ShortArray): Boolean {
        val c = connexion ?: return false
        return runCatching {
            val octets = ByteBuffer.allocate(pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN).apply { pcm.forEach { putShort(it) } }.array()
            val requete = Request.Builder().url("${reglages.serveur}/api/reveil/verifier")
                .header("Authorization", "Bearer ${reglages.jeton}")
                .post(octets.toRequestBody("application/octet-stream".toMediaType())).build()
            c.http.newCall(requete).execute().use { JSONObject(it.body.string()).optBoolean("jarvis") }
        }.getOrDefault(false)
    }

    // --- Notifications --------------------------------------------------------------------

    private fun creerCanaux() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CANAL_PERMANENT, "Connexion à Jarvis", NotificationManager.IMPORTANCE_MIN))
        nm.createNotificationChannel(NotificationChannel(CANAL_NOTIFICATIONS, "Notifications de Jarvis", NotificationManager.IMPORTANCE_HIGH))
        nm.createNotificationChannel(NotificationChannel(CANAL_CONFIRMATIONS, "Confirmations", NotificationManager.IMPORTANCE_HIGH))
    }

    private fun ouvrirAppli(): PendingIntent = PendingIntent.getActivity(this, 0,
        Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)

    private fun notificationPermanente(): Notification = NotificationCompat.Builder(this, CANAL_PERMANENT)
        .setSmallIcon(R.drawable.ic_jarvis)
        .setContentTitle("Jarvis")
        .setContentText(if (reglages.reveilActif) "À l'écoute de « Jarvis »" else "Connecté au PC")
        .setOngoing(true)
        .setContentIntent(ouvrirAppli())
        .build()

    private var compteurNotifications = 10

    private fun notifier(titre: String, texte: String, action: Intent?, canal: String) {
        val intention = action?.let { PendingIntent.getActivity(this, compteurNotifications, it, PendingIntent.FLAG_IMMUTABLE) } ?: ouvrirAppli()
        val n = NotificationCompat.Builder(this, canal)
            .setSmallIcon(R.drawable.ic_jarvis)
            .setContentTitle(titre)
            .setContentText(texte)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texte))
            .setAutoCancel(true)
            .setContentIntent(intention)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        runCatching { getSystemService(NotificationManager::class.java).notify(compteurNotifications++, n) }
    }

    companion object {
        const val CANAL_PERMANENT = "permanent"
        const val CANAL_NOTIFICATIONS = "notifications"
        const val CANAL_CONFIRMATIONS = "confirmations"
        @Volatile var instance: JarvisService? = null

        const val EXTRA_SANS_MICRO = "sans_micro"

        fun demarrer(context: Context, sansMicro: Boolean = false) {
            val intention = Intent(context, JarvisService::class.java).putExtra(EXTRA_SANS_MICRO, sansMicro)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intention) else context.startService(intention)
        }
    }
}
