# À lancer ou à vérifier sur le PC de jeu

Tout ce qui dépend du GPU, du micro ou de la latence ne se valide que sur le PC de jeu. Pour
chaque point : quoi lancer, comment, résultat attendu, quoi me renvoyer. Les points sont
dans l'ordre conseillé.

---

## V0 — Récupérer le projet et installer

1. `git pull` dans le dossier Jarvis.
2. Python 3.13 : `winget install Python.Python.3.13` (si absent).
3. Pilote AMD Adrenalin à jour (il fournit Vulkan).

## V0-1 — Diagnostic (lot J0) · **prioritaire : il tranche les modèles**

**Durée** : 10 min de présence (dont 2 au micro), puis 1 à 2 h automatiques. ~45 Go sur un NVMe.

```
diagnostic.cmd --donnees D:\Jarvis
```

- Répondre `o` au téléchargement, suivre l'étape micro (silence, « Hey Jarvis » ×2, « Jarvis »
  seul ×2, une phrase sans le mot, 5 phrases à lire), puis laisser tourner sans jouer.
- **Attendu** : « llama.cpp voit : Vulkan0: AMD Radeon RX 6750 XT » ; modèles 9-14 G à 30-60
  jetons/s ; « Mémoire » sous 11 Go ; rapport dans `diagnostic-resultats\<date>\rapport.md`.
- **À me renvoyer** : `rapport.md` et `diagnostic.json` (pas les dossiers `micro\` et `corpus\`,
  qui contiennent ta voix) ; ton classement des voix (`ecoute\*.wav`) ; le modèle qui parle le
  mieux français selon toi (section « Français » du rapport).
- Options : `--avec-moe` (Gemma 4 26B-A4B), `--avec-rocm`, `--sans-micro`, `--etapes llm`.

## V1-1 — Installer et lancer Jarvis

```
installer.cmd -Demarrage
jarvis.cmd --fenetre
```

- Si le diagnostic a choisi d'autres modèles que les valeurs provisoires, les reporter dans
  `%LOCALAPPDATA%\Jarvis\jarvis.toml` (section `[llm]`) puis relancer `installer.cmd`.
  Le dossier choisi au diagnostic (`--donnees D:\Jarvis`) est retenu : rien n'est retéléchargé.
- **Attendu** : icône Jarvis dans la zone de notification ; fenêtre d'interface ; tableau de
  bord : « Démarrage » ≤ 15 s (PERF-09).

## V1-2 — Boucle vocale (J1)

- Dire « Jarvis, quelle est la capitale de l'Australie ? » puis « Jarvis » seul, attendre le
  bip d'écoute… (il n'y a pas de bip : l'état « écoute… » s'affiche dans l'interface), poser
  une question.
- Couper la parole à Jarvis en disant « Jarvis » pendant qu'il parle.
- Enchaîner une deuxième question sans redire « Jarvis » dans les 6 secondes.
- **Attendu** : latence affichée dans le tableau de bord < 1 000 ms (cible PERF-01), < 1 500 ms
  au pire ; interruption immédiate ; pas de faux déclenchement pendant une soirée normale.
- **À me renvoyer** : les latences du tableau de bord ; « Jarvis » seul est-il reconnu ?
  combien de faux déclenchements sur une soirée ? (si trop : `seuil_reveil_bas` 0,15 → 0,25)

## V2-1 — Sécurité (J2)

- « Jarvis, supprime le fichier C:\Temp\test.txt » (créer le fichier avant) → Jarvis doit
  demander confirmation à la voix et dans l'interface ; répondre « non » → rien n'est supprimé.
- Pendant une réponse longue : **Ctrl+Alt+K** (arrêt d'urgence) → tout s'arrête.
- Interface → Journal : chaque action y figure avec la demande d'origine.

## V3-1 — Batterie de commandes et banc (J3, J11)

```
.venv\Scripts\python -m jarvis banc
```

- **Attendu** : `NF-02_taux_commandes` ≥ 0,90 ; PERF-01 ≤ 1 000 ms ; PERF-05 ≥ 40 jetons/s ;
  PERF-06 ≈ 0 ; PERF-07 < 2 % ; PERF-09 ≤ 15 s ; PERF-10 ≤ 3 s ; PERF-13 ≤ 50 ms.
- **À me renvoyer** : `banc-resultats\<date>\banc.md`.
- Essais utiles (une ligne dans `jarvis.toml`, puis relancer le banc) : `speculatif = "aucun"`
  puis `"mtp"` ; `cache_kv = "f16"` ; `anticipation_ms = 0`. On garde ce qui gagne sans faire
  baisser le taux de commandes.
- **Ta liste de commandes du quotidien** (une vingtaine pour commencer) : je l'intègre à la
  batterie (`src/jarvis/donnees/batterie_commandes.json`).

## V4-1 — Mémoire (J4)

- « Jarvis, retiens que je préfère jouer le soir après 21 h. » Une semaine plus tard : « À
  quelle heure je préfère jouer ? » → réponse juste.
- « Qu'est-ce que tu sais sur moi ? » puis « Oublie ce que tu sais sur mes horaires de jeu »
  (confirmation demandée) → plus aucune trace (interface → Mémoire).
- Sauvegarde : dans `jarvis.toml`, `[memoire] dossier_sauvegarde = 'E:\Sauvegardes\Jarvis'`
  (le disque de 4 To) ; puis `python -m jarvis sauvegarde --cle` et **noter la clé de secours
  hors du PC**.

## V5-1 — Téléphone et Mac (J5)

1. Installer Tailscale sur le PC, le téléphone et le Mac (même compte).
2. `installer.cmd -Tailscale` sur le PC → affiche l'adresse `https://<pc>.<tailnet>.ts.net`.
3. Sur le PC : icône Jarvis → « Appairer un appareil… » → code à 6 chiffres.
4. Sur le téléphone : ouvrir l'adresse, saisir le code, « Ajouter à l'écran d'accueil ».
- **Attendu** : discussion texte, appui long sur 🎙 pour parler, confirmations d'un clic, en
  Wi-Fi puis en 4G/5G (Wi-Fi coupé).
- Révocation : interface → Appareils → Révoquer → le téléphone est déconnecté aussitôt.

## V6-1 — Vision (J6)

- Ouvrir une fenêtre avec un message d'erreur, puis « Jarvis, qu'est-ce qui cloche sur mon
  écran ? » → description juste de l'erreur.
- « Cherche sur internet la date du prochain patch de CS2 » → réponse sourcée.
- Si `pip install -e .[navigateur]` : les pages dynamiques sont rendues par Edge.

## V7-1 — Brancher les comptes (J7) · **action de Mathieu**

Dans `jarvis.toml` section `[integrations]`, puis les secrets avec `python -m jarvis secrets definir <nom>` :

| Service | Configuration | Secret |
|---|---|---|
| Mail (Gmail : mot de passe d'application) | `imap_hote = "imap.gmail.com"`, `imap_utilisateur`, `smtp_hote = "smtp.gmail.com"` | `imap_mot_de_passe` |
| Agenda Google (lecture) | `ics_url` = « Adresse secrète au format iCal » de l'agenda | — |
| Agenda CalDAV (lecture + création : iCloud, Nextcloud…) | `caldav_url`, `caldav_utilisateur` | `caldav_mot_de_passe` |
| Discord | créer un bot (discord.com/developers), l'inviter sur ton serveur ; `discord_salons = { general = "id" }`, `discord_contacts = { "théo" = "id" }` | `discord_jeton_bot` |
| Spotify (Premium pour piloter la lecture) | créer une appli sur developer.spotify.com avec l'URL de retour `http://127.0.0.1:8730/connecter/spotify` ; puis dans l'interface… (à venir) ou `POST /api/connecter/spotify` | (jetons gérés par Jarvis) |
| Home Assistant | `home_assistant_url = "http://homeassistant.local:8123"` | `home_assistant_jeton` |

- **Attendu** : « J'ai des mails importants ? », « Qu'est-ce que j'ai aujourd'hui ? »,
  « Dis à Théo sur Discord que j'arrive » → toujours une confirmation avant l'envoi.

## V8-1 — Briefing (J8)

- Le matin, première activité au PC → briefing parlé (agenda, mails, rappels, météo).
- **Fini quand** : une semaine sans intervention.

## V9-1 — Mode jeu (J9)

- Lancer une partie de CS2 (ou de DM) : en moins de 3 s, l'interface affiche « mode : jeu » ;
  la VRAM utilisée par Jarvis tombe (Gestionnaire des tâches → Performances → GPU).
- Mesurer les FPS avec et sans Jarvis (même carte, même mode) : écart < 2 % (PERF-08).
- Pendant la partie : « Jarvis, quelle heure est-il ? » doit répondre (modèle CPU) ; un rappel
  autorisé est annoncé, une suggestion ne l'est pas.
- Postgame : dès que son API locale tourne, « Comment était ma dernière session de DM ? ».

## V12-1 — Multi-appareils (J12)

- PC au clavier : un rappel arrive sur le PC. PC inactif 10 min et téléphone utilisé : il
  arrive sur le téléphone ; non lu au bout d'un moment : relayé aux autres appareils.
- Depuis le téléphone : « Envoie-moi le fichier C:\Temp\test.pdf » → lien valable une fois.
- Une confirmation demandée depuis le téléphone ne peut pas être acceptée depuis le Mac.

## V13-1 — Application Android (J13) · **jamais compilée**

Suivre [android/README.md](android/README.md) (Android Studio, clé de signature hors dépôt).
- **Attendu** : appairage, notifications téléphone verrouillé, appui pour parler, tuile,
  confirmation par empreinte, « fais sonner mon téléphone » depuis le PC.
- **À me renvoyer** : les erreurs de compilation éventuelles (copier-coller), la mémoire du
  POCO (8 ou 12 Go) et l'autonomie avec le mot de réveil actif sur une journée.

## V14-1 — Mac (J14) · **jamais lancé sur un Mac**

```
git clone https://github.com/mathieu-ferrante/Jarvis && cd Jarvis && sh mac/installer.sh
```
- **Attendu** : icône dans la barre des menus ; ⌥⌘J pour parler ; depuis le PC, « ouvre Notes
  sur le Mac » ; PC éteint : « mode secours » annoncé et réponse locale.
- **À me renvoyer** : erreurs éventuelles, permissions macOS demandées.

## V15-1 — Contexte (J15)

- Activer la position dans l'appli Android, puis « Rappelle-moi d'acheter du pain quand
  j'arrive au Carrefour de <ta ville> » → notification en arrivant.
- « Rappelle-moi de m'étirer à la fin de ma partie » → rappel à la sortie du jeu.
- Commencer une conversation au PC, la poursuivre au téléphone : Jarvis a le fil.

## V16-1 — Voix (J16)

```
.venv\Scripts\python -m jarvis enroler-voix
.venv\Scripts\python -m jarvis entrainer-reveil
```
- `enroler-voix` : dire « Jarvis » et lire les phrases affichées (quelques minutes) ; il enregistre ta voix pour le mot
  de réveil et ton empreinte vocale (chiffrée dans le coffre).
- `entrainer-reveil` : quelques minutes (durée à noter) ; **attendu** : rappel ≥ 0,9 sur « Jarvis »,
  faux positifs bas sur les pièges ; `jarvis_perso.onnx` est pris au redémarrage.
- Interrompre Jarvis par « Jarvis » **sans casque**, haut-parleurs à volume normal.
- Demander à quelqu'un d'autre de répondre « oui » à une confirmation : refusé.
- **À me renvoyer** : le bilan affiché par `entrainer-reveil` ; faux déclenchements sur une soirée.

## V17-1 — Intelligence (J17)

- `python -m jarvis banc` : taux de la batterie de 200 commandes ≥ 0,90.
- `python -m jarvis evaluer gemma-4-12b` (ou un autre candidat) : recommandation affichée.
- « Prépare-moi un résumé de mes mails de la semaine dans un fichier » → tâche de fond avec
  compte rendu ; redémarrer Jarvis au milieu : elle reprend.
- Interface → Mémoire → Propositions : accepter ou refuser ce que Jarvis a déduit.
- Expérimental : « Coche l'option … dans les réglages de … » → pilotage de l'écran, confirmé.

## V18-1 — Initiative (J18)

- « Jarvis, sois plus discret » ou interface → Initiative : silencieux, discret, actif.
- En mode actif, une habitude acceptée (ex. Spotify vers 21 h) est proposée à l'heure.
- Pendant une partie de LoL ou CS2 avec Postgame lancé : « Un conseil ? » → conseil tiré de
  l'état en direct (si Postgame n'expose pas encore `/api/<jeu>/live`, Jarvis le dit).

---

## Valeurs provisoires

Voir [PLAN.md](PLAN.md) : elles servent à avancer, mais **rien n'est validé tant que ces
points n'ont pas tourné sur le PC de jeu**.
