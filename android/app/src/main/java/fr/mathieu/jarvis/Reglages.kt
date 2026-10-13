package fr.mathieu.jarvis

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Réglages de l'appli. Le jeton d'appareil est chiffré par une clé du Keystore Android
 * (matériel sécurisé, non exportable) : il ne quitte jamais le téléphone en clair.
 */
class Reglages(context: Context) {
    private val prefs = context.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    var serveur: String
        get() = prefs.getString("serveur", "") ?: ""
        set(v) = prefs.edit().putString("serveur", v.trim().trimEnd('/')).apply()

    var jeton: String?
        get() = prefs.getString("jeton", null)?.let { dechiffrer(it) }
        set(v) = prefs.edit().apply { if (v == null) remove("jeton") else putString("jeton", chiffrer(v)) }.apply()

    /** Identifiant de l'appareil : partie du jeton avant le point. */
    val identifiant: String get() = jeton?.substringBefore('.') ?: ""

    var reveilActif: Boolean
        get() = prefs.getBoolean("reveil", false)
        set(v) = prefs.edit().putBoolean("reveil", v).apply()

    var seuilBatterie: Int
        get() = prefs.getInt("seuil_batterie", 20)
        set(v) = prefs.edit().putInt("seuil_batterie", v).apply()

    /** TEL-06 : la position n'est partagée que si Mathieu l'a explicitement activée. */
    var positionAutorisee: Boolean
        get() = prefs.getBoolean("position", false)
        set(v) = prefs.edit().putBoolean("position", v).apply()

    /** TEL-07 : dernière vue gardée pour le mode hors connexion. */
    var derniereVue: String
        get() = prefs.getString("derniere_vue", "") ?: ""
        set(v) = prefs.edit().putString("derniere_vue", v).apply()

    private fun cle(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generateur = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generateur.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return generateur.generateKey()
    }

    private fun chiffrer(texte: String): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, cle()) }
        val donnees = c.iv + c.doFinal(texte.toByteArray())
        return Base64.encodeToString(donnees, Base64.NO_WRAP)
    }

    private fun dechiffrer(texte: String): String? = runCatching {
        val donnees = Base64.decode(texte, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, cle(), GCMParameterSpec(128, donnees, 0, 12))
        String(c.doFinal(donnees, 12, donnees.size - 12))
    }.getOrNull()

    private companion object {
        const val ALIAS = "jarvis_jeton"
    }
}
