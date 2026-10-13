package fr.mathieu.jarvis

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Connexion persistante au PC (TEL-04) via Tailscale : une seule WebSocket, gardée ouverte par le
 * service, reconnectée automatiquement. Aucun service de notification tiers (pas de Firebase).
 * Les messages écrits hors connexion sont mis en file et partent à la reconnexion (TEL-07).
 */
class Connexion(
    private val serveur: String,
    private val jeton: String,
    private val surMessage: (JSONObject) -> Unit,
) {
    val http: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(25, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var ws: WebSocket? = null
    @Volatile private var authentifiee = false
    @Volatile private var fermee = false
    private var delaiMs = 1000L
    private val enAttente = ConcurrentLinkedQueue<String>()
    private val planificateur = Executors.newSingleThreadScheduledExecutor()

    fun ouvrir() {
        if (fermee) return
        val url = serveur.replaceFirst("https://", "wss://").replaceFirst("http://", "ws://") + "/ws"
        ws = http.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(JSONObject().put("jeton", jeton).toString())
                authentifiee = true
                delaiMs = 1000L
                Etat.connecte.value = true
                while (true) webSocket.send(enAttente.poll() ?: break)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                runCatching { surMessage(JSONObject(text)) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = perdue(code)

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = perdue(0)
        })
    }

    private fun perdue(code: Int) {
        authentifiee = false
        Etat.connecte.value = false
        if (code == 4401) { // jeton révoqué depuis le PC (SEC-13)
            Etat.revoque.value = true
            return
        }
        if (!fermee) {
            planificateur.schedule({ ouvrir() }, delaiMs, TimeUnit.MILLISECONDS)
            delaiMs = (delaiMs * 2).coerceAtMost(30_000L)
        }
    }

    fun envoyer(message: JSONObject, mettreEnFile: Boolean = true) {
        val texte = message.toString()
        val envoye = authentifiee && ws?.send(texte) == true
        if (!envoye && mettreEnFile) enAttente.add(texte)
    }

    fun fermer() {
        fermee = true
        ws?.close(1000, null)
        planificateur.shutdownNow()
    }
}
