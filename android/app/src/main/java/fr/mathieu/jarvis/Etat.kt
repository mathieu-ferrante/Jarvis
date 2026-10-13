package fr.mathieu.jarvis

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONObject

data class Message(val de: String, val texte: String, val id: Long = System.nanoTime(), val enCours: Boolean = false)

data class Confirmation(val id: Int, val question: String, val arguments: String, val suiteContenuExterne: Boolean)

/** État partagé entre le service (connexion permanente) et l'interface. */
object Etat {
    val connecte = MutableStateFlow(false)
    val messages = MutableStateFlow<List<Message>>(emptyList())
    val confirmations = MutableStateFlow<List<Confirmation>>(emptyList())
    val etatVoix = MutableStateFlow("")
    val revoque = MutableStateFlow(false)
    @Volatile var auPremierPlan = false

    fun ajouter(de: String, texte: String) = messages.update { (it + Message(de, texte)).takeLast(200) }

    fun morceau(texte: String) = messages.update { liste ->
        val dernier = liste.lastOrNull()
        if (dernier != null && dernier.de == "jarvis" && dernier.enCours) liste.dropLast(1) + dernier.copy(texte = dernier.texte + texte)
        else liste + Message("jarvis", texte, enCours = true)
    }

    fun finReponse() = messages.update { l -> l.map { if (it.enCours) it.copy(enCours = false) else it } }

    fun ajouterConfirmation(d: JSONObject) = confirmations.update {
        it + Confirmation(d.getInt("id"), d.optString("question"), d.optJSONObject("arguments")?.toString(2) ?: "{}",
            d.optBoolean("suite_contenu_externe"))
    }

    fun retirerConfirmation(id: Int) = confirmations.update { l -> l.filterNot { it.id == id } }
}
