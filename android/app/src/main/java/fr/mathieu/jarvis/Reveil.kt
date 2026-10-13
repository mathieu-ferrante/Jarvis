package fr.mathieu.jarvis

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.BatteryManager
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.nio.FloatBuffer

/**
 * Mot de réveil sur le téléphone (TEL-02) : portage fidèle du pipeline openWakeWord
 * (spectrogramme de Mel → plongements « speech_embedding » → modèle « hey jarvis »), exécuté
 * localement par ONNX Runtime. Les modèles viennent du PC (API authentifiée), pas d'Internet.
 *
 * Second étage comme au PC (D6) : un score « possible » envoie les 1,6 dernières secondes au PC,
 * qui vérifie par transcription que « Jarvis » a bien été prononcé. Rien n'est envoyé sinon.
 * Coupé automatiquement sous le seuil de batterie (hors charge) — PERF-11.
 */
class Reveil(
    private val context: Context,
    private val reglages: Reglages,
    private val http: OkHttpClient,
    private val verifier: (ShortArray) -> Boolean,
    private val surReveil: () -> Unit,
) {
    private val env = OrtEnvironment.getEnvironment()
    private var melspec: OrtSession? = null
    private var embedding: OrtSession? = null
    private var modele: OrtSession? = null
    @Volatile private var actif = false
    private var fil: Thread? = null

    private val melBuffer = ArrayDeque<FloatArray>()  // trames de 32 valeurs
    private val embBuffer = ArrayDeque<FloatArray>()  // plongements de 96 valeurs
    // Anneau de 2 s d'audio (sans objets intermédiaires : sobre en batterie)
    private val anneau = ShortArray(32_000)
    private var ecrits = 0L

    private fun derniers(n: Int): ShortArray {
        val sortie = ShortArray(n)
        val debut = ecrits - n
        for (i in 0 until n) sortie[i] = anneau[((debut + i) % anneau.size).toInt()]
        return sortie
    }

    fun demarrer(): Boolean {
        if (actif) return true
        if (!chargerModeles()) return false
        actif = true
        fil = Thread({ boucle() }, "jarvis-reveil").apply { priority = Thread.NORM_PRIORITY - 1; start() }
        return true
    }

    fun arreter() {
        actif = false
        fil?.join(500)
    }

    private fun chargerModeles(): Boolean = runCatching {
        fun charger(nom: String): OrtSession {
            val f = File(context.filesDir, nom)
            if (!f.exists()) telecharger(nom, f)
            return env.createSession(f.absolutePath, OrtSession.SessionOptions().apply { setIntraOpNumThreads(1) })
        }
        melspec = charger("melspectrogram.onnx")
        embedding = charger("embedding_model.onnx")
        modele = charger("hey_jarvis_v0.1.onnx")
        true
    }.getOrDefault(false)

    private fun telecharger(nom: String, destination: File) {
        val requete = Request.Builder().url("${reglages.serveur}/api/modeles/reveil/$nom")
            .header("Authorization", "Bearer ${reglages.jeton}").build()
        http.newCall(requete).execute().use { rep ->
            check(rep.isSuccessful) { "modèle $nom indisponible (${rep.code})" }
            destination.outputStream().use { rep.body.byteStream().copyTo(it) }
        }
    }

    private fun batterieSuffisante(): Boolean {
        val bm = context.getSystemService(BatteryManager::class.java)
        return bm.isCharging || bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) >= reglages.seuilBatterie
    }

    @SuppressLint("MissingPermission")
    private fun boucle() {
        val taille = AudioRecord.getMinBufferSize(16_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val micro = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16_000, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(taille, TRAME * 4))
        repeat(76) { melBuffer.addLast(FloatArray(32) { 1f }) }
        val trame = ShortArray(TRAME)
        var derniereVerif = 0L
        var compteurBatterie = 0
        micro.startRecording()
        try {
            while (actif) {
                if (micro.read(trame, 0, TRAME) != TRAME) continue
                if (++compteurBatterie % 750 == 0 && !batterieSuffisante()) { // vérifié chaque minute
                    Etat.ajouter("systeme", "Mot de réveil coupé : batterie sous ${reglages.seuilBatterie} %.")
                    break
                }
                for (echantillon in trame) anneau[(ecrits++ % anneau.size).toInt()] = echantillon
                val score = traiter() ?: continue
                val maintenant = System.currentTimeMillis()
                if (score >= SEUIL || (score >= SEUIL_BAS && maintenant - derniereVerif > 1500 && verifierAudio().also { derniereVerif = maintenant })) {
                    micro.stop()
                    reinitialiser()
                    surReveil()
                    Thread.sleep(500)
                    if (actif) micro.startRecording()
                }
            }
        } finally {
            runCatching { micro.stop() }
            micro.release()
            actif = false
        }
    }

    private fun verifierAudio(): Boolean = verifier(derniers(16_000 * 16 / 10))

    private fun reinitialiser() {
        embBuffer.clear()
        melBuffer.clear()
        repeat(76) { melBuffer.addLast(FloatArray(32) { 1f }) }
    }

    /** Traite les 80 dernières ms ; renvoie le score du mot de réveil (ou null tant que le tampon se remplit). */
    private fun traiter(): Float? {
        if (ecrits < TRAME + 480) return null
        // 1. Spectrogramme de Mel des 1 760 derniers échantillons (valeurs int16 en float), puis x/10 + 2
        val pcm = derniers(TRAME + 480)
        val audio = FloatArray(pcm.size) { pcm[it].toFloat() }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(audio), longArrayOf(1, audio.size.toLong())).use { t ->
            melspec!!.run(mapOf(melspec!!.inputNames.first() to t)).use { r ->
                @Suppress("UNCHECKED_CAST")
                val sortie = r[0].value as Array<Array<Array<FloatArray>>>  // [trames][1][?][32]
                for (trameMel in sortie) {
                    val v = trameMel[0][0]
                    melBuffer.addLast(FloatArray(32) { v[it] / 10f + 2f })
                }
            }
        }
        while (melBuffer.size > 970) melBuffer.removeFirst()
        // 2. Plongement de la fenêtre des 76 dernières trames
        val fenetre = FloatArray(76 * 32)
        melBuffer.toList().takeLast(76).forEachIndexed { i, f -> f.copyInto(fenetre, i * 32) }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(fenetre), longArrayOf(1, 76, 32, 1)).use { t ->
            embedding!!.run(mapOf(embedding!!.inputNames.first() to t)).use { r ->
                @Suppress("UNCHECKED_CAST")
                val e = (r[0].value as Array<Array<Array<FloatArray>>>)[0][0][0]
                embBuffer.addLast(e.copyOf())
            }
        }
        while (embBuffer.size > 16) embBuffer.removeFirst()
        if (embBuffer.size < 16) return null
        // 3. Modèle « hey jarvis » sur les 16 derniers plongements
        val entree = FloatArray(16 * 96)
        embBuffer.forEachIndexed { i, e -> e.copyInto(entree, i * 96) }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(entree), longArrayOf(1, 16, 96)).use { t ->
            modele!!.run(mapOf(modele!!.inputNames.first() to t)).use { r ->
                @Suppress("UNCHECKED_CAST")
                return (r[0].value as Array<FloatArray>)[0][0]
            }
        }
    }

    private companion object {
        const val TRAME = 1280
        const val SEUIL = 0.5f
        const val SEUIL_BAS = 0.15f
    }
}
