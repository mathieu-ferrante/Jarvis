package fr.mathieu.jarvis

import android.content.Context
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.util.Base64
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Appui pour parler (TEL-03) : enregistrement en Ogg/Opus (compact, PERF-03/04), envoi au PC,
 * puis lecture de la réponse parlée renvoyée par le PC. Rien n'est traité ailleurs que sur le PC.
 */
class Enregistreur(private val context: Context, private val reglages: Reglages) {
    private var enregistreur: MediaRecorder? = null
    private var fichier: File? = null
    private val http = OkHttpClient.Builder().callTimeout(90, TimeUnit.SECONDS).build()
    val enCours get() = enregistreur != null

    fun commencer() {
        if (enregistreur != null) return
        val f = File.createTempFile("parole", ".ogg", context.cacheDir)
        val r = MediaRecorder(context).apply {
            setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            setOutputFormat(MediaRecorder.OutputFormat.OGG)
            setAudioEncoder(MediaRecorder.AudioEncoder.OPUS)
            setAudioSamplingRate(16_000)
            setAudioChannels(1)
            setAudioEncodingBitRate(24_000)
            setOutputFile(f)
            prepare()
            start()
        }
        enregistreur = r
        fichier = f
        Etat.etatVoix.value = "écoute…"
    }

    /** Arrête et envoie ; `surReponse(transcription, réponse)` est appelé sur un fil d'arrière-plan. */
    fun terminer(surReponse: (String, String) -> Unit) {
        val r = enregistreur ?: return
        val f = fichier
        enregistreur = null
        runCatching { r.stop() }
        r.release()
        if (f == null || f.length() < 1500) {
            Etat.etatVoix.value = ""
            f?.delete()
            return
        }
        Etat.etatVoix.value = "réfléchit…"
        Thread { envoyer(f, surReponse) }.start()
    }

    private fun envoyer(f: File, surReponse: (String, String) -> Unit) {
        try {
            val corps = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("fichier", "parole.ogg", f.asRequestBody("audio/ogg".toMediaType()))
                .build()
            val requete = Request.Builder().url("${reglages.serveur}/api/audio")
                .header("Authorization", "Bearer ${reglages.jeton}").post(corps).build()
            http.newCall(requete).execute().use { rep ->
                if (!rep.isSuccessful) {
                    surReponse("", "Jarvis a répondu ${rep.code}.")
                    return
                }
                val json = JSONObject(rep.body.string())
                surReponse(json.optString("transcription"), json.optString("reponse"))
                json.optString("audio_wav_b64").takeIf { it.isNotEmpty() }?.let { jouer(it) }
            }
        } catch (e: Exception) {
            surReponse("", "Jarvis est injoignable (${e.javaClass.simpleName}).")
        } finally {
            f.delete()
            Etat.etatVoix.value = ""
        }
    }

    private fun jouer(wavBase64: String) {
        val sortie = File.createTempFile("reponse", ".wav", context.cacheDir)
        sortie.writeBytes(Base64.decode(wavBase64, Base64.DEFAULT))
        MediaPlayer().apply {
            setDataSource(sortie.absolutePath)
            setOnCompletionListener { it.release(); sortie.delete() }
            prepare()
            start()
        }
        Etat.etatVoix.value = "parle"
    }
}
