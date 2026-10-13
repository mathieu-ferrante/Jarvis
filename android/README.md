# Jarvis — application Android (lot J13)

Application native Kotlin (Jetpack Compose) pour le POCO M7 Pro. **Écrite sur le poste de
développement, où Gradle est bloqué : elle n'a jamais été compilée.** La première compilation
se fait sur le PC de jeu ; attends-toi à quelques corrections mineures (versions, imports).

## Ce qu'elle fait

| Exigence | Réalisation |
|---|---|
| TEL-01 | APK installé directement, sans Play Store ; la PWA reste en secours |
| TEL-02 | Mot de réveil « Jarvis » sur le téléphone : modèles openWakeWord (ONNX Runtime), récupérés auprès du PC ; vérification de « Jarvis » seul par le PC ; coupé sous un seuil de batterie |
| TEL-03 | Appui pour parler (Ogg/Opus), tuile des réglages rapides |
| TEL-04 | Notifications par la connexion WebSocket directe avec le PC (Tailscale), sans Firebase |
| TEL-05 / SEC-12 | Confirmations d'un tap + empreinte (BiometricPrompt) ; le PC refuse un « oui » d'Android sans empreinte |
| TEL-06 | Position seulement si activée dans les réglages, arrondie à ~100 m |
| TEL-07 | File d'attente des messages hors connexion, derniers rappels gardés |
| TEL-08 | Écran guidé HyperOS (démarrage automatique, batterie, verrouillage dans les récents) |
| MULTI-04 | Outils du téléphone exposés au cerveau : sonner, batterie, lampe, ouvrir un lien, position |
| SEC-15 | Signature avec ta clé, lue depuis `keystore.properties` (hors dépôt) |

## Compiler (sur le PC de jeu)

1. Installer **Android Studio** (il fournit le JDK et le SDK).
2. *File → Open* → le dossier `android/`. Laisser la synchronisation Gradle se faire (elle
   génère le `gradle-wrapper.jar` manquant). Si Android Studio propose une mise à jour de
   l'Android Gradle Plugin ou de Kotlin, accepter.
3. Clé de signature (une fois, à garder hors du dépôt et sauvegardée) :
   ```
   keytool -genkeypair -v -keystore D:\Cles\jarvis.jks -alias jarvis -keyalg RSA -keysize 4096 -validity 10000
   ```
   puis copier `keystore.properties.exemple` en `keystore.properties` et le remplir.
4. *Build → Generate Signed App Bundle / APK → APK → release*.
5. Sur le POCO : activer le mode développeur et le débogage USB, puis
   `adb install app-release.apk` (ou copier l'APK et l'ouvrir).

## Premier lancement

1. Tailscale actif sur le téléphone et le PC ; `installer.cmd -Tailscale` fait sur le PC.
2. Ouvrir Jarvis → adresse `https://<pc>.<tailnet>.ts.net` → code d'appairage affiché par le PC.
3. Onglet Réglages → suivre le guide HyperOS (sinon HyperOS coupe l'appli en arrière-plan).
4. Activer le mot de réveil si voulu (notification permanente : exigée par Android).

## Limites connues

- L'audio part à la fin de l'appui (pas encore en flux pendant la parole) ; l'écoute après le
  mot de réveil dure 5 s fixes.
- Au démarrage du téléphone, Android interdit d'ouvrir le micro en arrière-plan : le mot de
  réveil reprend à la première ouverture de l'appli.
