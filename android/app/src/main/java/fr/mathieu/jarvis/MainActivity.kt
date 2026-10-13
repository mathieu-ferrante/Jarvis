package fr.mathieu.jarvis

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

private val Fond = Color(0xFF0B1020)
private val Surface1 = Color(0xFF131A2E)
private val Accent = Color(0xFF40C4FF)
private val Danger = Color(0xFFFF5C7A)

class MainActivity : FragmentActivity() {
    private lateinit var reglages: Reglages
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        reglages = Reglages(this)
        permissions.launch(arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS))
        if (reglages.jeton != null) JarvisService.demarrer(this)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Accent, background = Fond, surface = Surface1)) {
                var appaire by remember { mutableStateOf(reglages.jeton != null) }
                val revoque by Etat.revoque.collectAsState()
                if (revoque) {
                    reglages.jeton = null
                    Etat.revoque.value = false
                    appaire = false
                }
                Surface(Modifier.fillMaxSize(), color = Fond) {
                    if (!appaire) Appairage { appaire = true; JarvisService.demarrer(this) }
                    else Principal()
                }
            }
        }
        if (intent?.getBooleanExtra(EXTRA_PARLER, false) == true) JarvisService.instance?.commencerParole()
    }

    override fun onResume() { super.onResume(); Etat.auPremierPlan = true }
    override fun onPause() { super.onPause(); Etat.auPremierPlan = false }

    // --- Appairage (SEC-10) ---------------------------------------------------------------

    @Composable
    private fun Appairage(surAppaire: () -> Unit) {
        var serveur by remember { mutableStateOf(reglages.serveur.ifEmpty { "https://" }) }
        var code by remember { mutableStateOf("") }
        var erreur by remember { mutableStateOf("") }
        var envoi by remember { mutableStateOf(false) }
        Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
            Text("Jarvis", style = MaterialTheme.typography.headlineLarge, color = Accent)
            Spacer(Modifier.height(8.dp))
            Text("Tailscale doit être actif. Sur le PC : icône Jarvis → « Appairer un appareil… ».", color = Color.Gray)
            Spacer(Modifier.height(16.dp))
            OutlinedTextField(serveur, { serveur = it }, label = { Text("Adresse du PC (https://…ts.net)") }, singleLine = true,
                modifier = Modifier.fillMaxWidth())
            OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, label = { Text("Code à 6 chiffres") },
                singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(16.dp))
            Button(enabled = code.length == 6 && !envoi, onClick = {
                envoi = true
                erreur = ""
                Thread {
                    val resultat = runCatching {
                        val corps = JSONObject().put("code", code).put("nom", "${android.os.Build.MODEL}").put("type", "android")
                        val req = Request.Builder().url(serveur.trimEnd('/') + "/api/appairer")
                            .post(corps.toString().toRequestBody("application/json".toMediaType())).build()
                        OkHttpClient().newCall(req).execute().use { rep ->
                            check(rep.isSuccessful) { if (rep.code == 403) "Code invalide ou expiré" else "Erreur ${rep.code}" }
                            JSONObject(rep.body.string()).getString("jeton")
                        }
                    }
                    runOnUiThread {
                        envoi = false
                        resultat.onSuccess { reglages.serveur = serveur; reglages.jeton = it; surAppaire() }
                            .onFailure { erreur = it.message ?: "Jarvis est injoignable" }
                    }
                }.start()
            }, modifier = Modifier.fillMaxWidth()) { Text(if (envoi) "…" else "Appairer") }
            if (erreur.isNotEmpty()) Text(erreur, color = Danger, modifier = Modifier.padding(top = 8.dp))
        }
    }

    // --- Écran principal ------------------------------------------------------------------

    @Composable
    private fun Principal() {
        var onglet by remember { mutableIntStateOf(0) }
        val connecte by Etat.connecte.collectAsState()
        val etatVoix by Etat.etatVoix.collectAsState()
        val confirmations by Etat.confirmations.collectAsState()
        Column(Modifier.fillMaxSize().systemBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).background(if (connecte) Color(0xFF3DDC97) else Danger, CircleShape))
                Spacer(Modifier.width(8.dp))
                Text("Jarvis", style = MaterialTheme.typography.titleMedium)
                if (etatVoix.isNotEmpty()) Text("  $etatVoix", color = Color.Gray)
                Spacer(Modifier.weight(1f))
                Button(onClick = { JarvisService.instance?.arretUrgence() }, colors = ButtonDefaults.buttonColors(containerColor = Danger)) { Text("■ Stop") }
            }
            TabRow(selectedTabIndex = onglet, containerColor = Fond) {
                Tab(onglet == 0, { onglet = 0 }, text = { Text("Discussion") })
                Tab(onglet == 1, { onglet = 1 }, text = { Text("Réglages") })
            }
            if (onglet == 0) Discussion(connecte) else Parametres()
        }
        confirmations.firstOrNull()?.let { DialogueConfirmation(it) }
    }

    @Composable
    private fun ColumnScope.Discussion(connecte: Boolean) {
        val messages by Etat.messages.collectAsState()
        var texte by remember { mutableStateOf("") }
        var parle by remember { mutableStateOf(false) }
        val liste = rememberLazyListState()
        LaunchedEffect(messages.size) { if (messages.isNotEmpty()) liste.animateScrollToItem(messages.size - 1) }
        if (!connecte && reglages.derniereVue.isNotEmpty()) {
            Text("Hors connexion — dernière vue : ${reglages.derniereVue}", color = Color.Gray, modifier = Modifier.padding(12.dp))
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp), state = liste) {
            items(messages, key = { it.id }) { m ->
                val moi = m.de == "moi"
                Box(Modifier.fillMaxWidth().padding(vertical = 4.dp), contentAlignment = if (moi) Alignment.CenterEnd else Alignment.CenterStart) {
                    Text(m.texte, color = if (moi) Fond else if (m.de == "systeme") Color.Gray else Color.White,
                        modifier = Modifier.background(if (moi) Accent else if (m.de == "systeme") Color.Transparent else Surface1,
                            RoundedCornerShape(14.dp)).padding(10.dp))
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(56.dp).background(if (parle) Danger else Surface1, CircleShape)
                .pointerInput(Unit) {
                    detectTapGestures(onPress = {
                        parle = true
                        JarvisService.instance?.commencerParole()
                        tryAwaitRelease()
                        parle = false
                        JarvisService.instance?.terminerParole()
                    })
                }, contentAlignment = Alignment.Center) { Text("🎙") }
            Spacer(Modifier.width(8.dp))
            OutlinedTextField(texte, { texte = it }, placeholder = { Text("Écrire à Jarvis…") }, modifier = Modifier.weight(1f), singleLine = true)
            Spacer(Modifier.width(8.dp))
            Button(enabled = texte.isNotBlank(), onClick = { JarvisService.instance?.envoyerTexte(texte.trim()); texte = "" }) { Text("Envoyer") }
        }
    }

    // --- Confirmations biométriques (TEL-05, SEC-12) --------------------------------------

    @Composable
    private fun DialogueConfirmation(c: Confirmation) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Confirmer ?") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Text(c.question)
                    if (c.suiteContenuExterne) Text("⚠ Proposée à la suite d'un contenu lu, pas d'une demande directe.", color = Color(0xFFFFB547))
                    Text(c.arguments, color = Color.Gray, style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { Button(onClick = { demanderEmpreinte(c) }) { Text("Oui (empreinte)") } },
            dismissButton = { TextButton(onClick = { JarvisService.instance?.confirmer(c.id, oui = false, biometrie = false) }) { Text("Non") } },
        )
    }

    private fun demanderEmpreinte(c: Confirmation) {
        val invite = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                JarvisService.instance?.confirmer(c.id, oui = true, biometrie = true)
            }
        })
        invite.authenticate(BiometricPrompt.PromptInfo.Builder()
            .setTitle("Confirmer l'action de Jarvis")
            .setSubtitle(c.question.take(120))
            .setAllowedAuthenticators(BIOMETRIC_STRONG or DEVICE_CREDENTIAL)
            .build())
    }

    // --- Réglages et guide HyperOS (TEL-08) -----------------------------------------------

    @Composable
    private fun Parametres() {
        var reveil by remember { mutableStateOf(reglages.reveilActif) }
        var position by remember { mutableStateOf(reglages.positionAutorisee) }
        var seuil by remember { mutableFloatStateOf(reglages.seuilBatterie.toFloat()) }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Ligne("Mot de réveil « Jarvis » sur le téléphone", reveil) {
                reveil = it; reglages.reveilActif = it
                JarvisService.demarrer(this@MainActivity)
            }
            Text("Coupé sous ${seuil.toInt()} % de batterie (hors charge)", color = Color.Gray)
            Slider(seuil, { seuil = it; reglages.seuilBatterie = it.toInt() }, valueRange = 5f..60f)
            Ligne("Partager la position avec Jarvis (rappels de lieu)", position) {
                position = it; reglages.positionAutorisee = it
                if (it) permissions.launch(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION))
            }
            HorizontalDivider()
            Text("HyperOS : pour que Jarvis reste connecté", style = MaterialTheme.typography.titleMedium)
            Text("1. Autoriser le démarrage automatique.\n2. Retirer les restrictions de batterie (« Aucune restriction »).\n" +
                "3. Dans les applis récentes, appui long sur Jarvis → cadenas.", color = Color.Gray)
            Button(onClick = { ouvrir(Intent().setComponent(ComponentName("com.miui.securitycenter",
                "com.miui.permcenter.autostart.AutoStartManagementActivity"))) }) { Text("Démarrage automatique") }
            Button(onClick = { ouvrir(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))) }) {
                Text("Batterie : aucune restriction")
            }
            Button(onClick = { ouvrir(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }) {
                Text("Paramètres de l'appli")
            }
            HorizontalDivider()
            TextButton(onClick = { reglages.jeton = null; finishAffinity() }) { Text("Se déconnecter de ce PC", color = Danger) }
        }
    }

    @Composable
    private fun Ligne(libelle: String, valeur: Boolean, changement: (Boolean) -> Unit) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(libelle, Modifier.weight(1f))
            Switch(valeur, changement)
        }
    }

    private fun ouvrir(intention: Intent) {
        runCatching { startActivity(intention) }.onFailure {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
    }

    companion object {
        const val EXTRA_PARLER = "parler"
    }
}
