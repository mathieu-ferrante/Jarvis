# Jarvis — plan et suivi

Références : [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md) (lots J0 à J10) et
[CAHIER_DES_CHARGES_EXTENSIONS.md](CAHIER_DES_CHARGES_EXTENSIONS.md) (lots J11 à J18).
Ce que Mathieu doit lancer sur le PC de jeu : [A_VALIDER.md](A_VALIDER.md).

Légende : `[x]` fait et validé · `[~]` **codé et testé sur le poste de développement, PAS encore
validé sur le PC de jeu** · `[ ]` à faire.

> Rien n'a encore tourné sur le PC de jeu. Toutes les mesures citées ici viennent du poste de
> développement (i5-1335U, Iris Xe, modèle de test de 0,8 G) : elles valident le code, pas les
> performances, qui seront bien meilleures sur le Ryzen 5800X + RX 6750 XT.

## Avancement des lots

| Lot | État | Ce qui reste à valider sur le PC de jeu |
|---|---|---|
| J0 — Diagnostic et choix par la mesure | `[~]` | V0-1 : lancer le diagnostic, trancher les modèles |
| J1 — Boucle vocale | `[~]` | V1-2 : latence réelle, mot de réveil avec la voix de Mathieu |
| J2 — Cœur et sécurité | `[~]` | V2-1 : arrêt d'urgence (raccourci), confirmations à la voix |
| J3 — Outils PC | `[~]` | V3-1 : batterie de commandes ≥ 90 % avec le vrai modèle |
| J4 — Mémoire | `[~]` | V4-1 : souvenir gardé d'une semaine sur l'autre, oubli |
| J5 — Interface et téléphone | `[~]` | V5-1 : téléphone hors de chez soi via Tailscale |
| J6 — Web et vision | `[~]` | V6-1 : « qu'est-ce qui cloche sur mon écran ? » |
| J7 — Communication | `[~]` | V7-1 : brancher mail / agenda / Discord / Spotify |
| J8 — Initiative | `[~]` | V8-1 : briefing une semaine sans intervention |
| J9 — Coach de jeux et projets | `[~]` | V9-1 : mode jeu dans CS2 ; Postgame dès que son API existe |
| J10 — Maison connectée | `[~]` | Seulement si Home Assistant est installé |
| J11 — Optimisation du socle | `[~]` | V11-1 : banc de performance sur le PC de jeu |
| J12 — Socle multi-appareils | `[~]` | V12-1 : notifications routées, outils distants |
| J13 — Application Android | `[~]` | **Jamais compilée** (Gradle bloqué) : V13-1 compiler et installer sur le POCO |
| J14 — Mac | `[~]` | **Jamais lancé sur un Mac** : V14-1 |
| J15 — Contexte et continuité | `[~]` | V15-1 : rappel en arrivant quelque part |
| J16 — Voix maximum | `[~]` | V16-1 : enrôlement, réveil perso, écho, locuteur avec la vraie voix |
| J17 — Intelligence maximum | `[~]` | V17-1 : batterie de 200 avec le vrai modèle, `evaluer` |
| J18 — Initiative maximum | `[~]` | V18-1 : proactivité, coach en direct (Postgame) |

## Ce qui est en place (poste de développement : 185 tests verts)

- **J0** : diagnostic complet (`diagnostic.cmd`) : modèles (débit, latence, batterie d'outils,
  français, vision), transcription, voix, mot de réveil, micro ; décisions par règles explicites.
- **J1** : boucle vocale veille → écoute → réflexion → parole ; interruption, écoute continue,
  confirmation à la voix ; Parakeet v3 (onnx-asr), Piper, openWakeWord + vérification de
  « Jarvis » par la transcription, Silero. Bout en bout réel sur le poste de dev : 1,8 s.
- **J2** : orchestrateur (agent multi-étapes, vérification, honnêteté), registre de modules
  d'outils, permissions à 3 niveaux, contenu lu = donnée, journal, arrêt d'urgence, tâches de
  fond, garde réseau (crochet d'audit, liste blanche par outil, liste noire des fournisseurs
  d'IA), coffre DPAPI, test anti-fuite automatisé.
- **J3** : ~60 outils (système, fichiers, médias, routines, rappels, code en bac à sable…).
- **J4** : mémoire (faits datés et sourcés, recherche hybride, historique, oubli réel,
  documents indexés, souvenirs déduits automatiquement, sauvegarde chiffrée AES-GCM).
- **J5** : API FastAPI + WebSocket (127.0.0.1), appairage par code, jetons révocables, PWA
  React, icône de la zone de notification, raccourcis globaux, installeur, démarrage auto.
- **J6** : recherche web (DuckDuckGo), lecture de pages, vision d'écran et d'images.
- **J7** : mail IMAP/SMTP, agenda CalDAV ou iCal, Discord ; envois toujours confirmés.
- **J8** : briefing à la première activité du jour, suggestions plafonnées, sauvegarde auto.
- **J9** : mode jeu (VRAM libérée, petit modèle sur CPU, priorité basse, silence), Postgame
  (découverte de son API), projets perso (git, tests).
- **J10** : Home Assistant (actions courantes annoncées, sécurité toujours confirmée).
- **J11** : banc `python -m jarvis banc`, chemin rapide des commandes fréquentes, deux
  emplacements llama-server, cache des plongements, transcription anticipée.
- **J12** : présence (PC actif ou en jeu, sinon dernier appareil), notifications routées puis
  relayées si non lues, outils distants déclarés par les appareils (mêmes permissions),
  confirmation réservée à l'appareil d'origine ou au PC, envoi de fichiers par lien unique.
- **J13** : appli Android Kotlin/Compose (appairage, WebSocket en service de premier plan,
  appui pour parler, tuile, empreinte, outils du téléphone, mot de réveil ONNX, file hors
  connexion, guide HyperOS). **Non compilée.**
- **J14** : agent macOS (`python -m jarvis.mac`) : barre des menus, ⌥⌘J, outils du Mac,
  secours local Metal si le PC est injoignable. **Non testé sur un Mac.**
- **J15** : rappels à un lieu (géocodage OpenStreetMap, position du téléphone sur accord),
  à l'usage d'un appareil, à la fin d'une partie ; conversation commune à tous les appareils.
- **J16** : mot de réveil « Jarvis » personnalisé (`enroler-voix`, `entrainer-reveil`),
  empreinte du locuteur (WeSpeaker), annulation d'écho (25 à 40 dB sur le poste de dev).
- **J17** : batterie de 200 commandes, tâches de fond planifiées et reprises après
  redémarrage, personnalisation par exemples (D21), souvenirs et habitudes proposés (D22),
  `python -m jarvis evaluer <modèle>`, agent de pilotage de l'écran (expérimental).
- **J18** : proactivité réglable (silencieux, discret, actif) à la voix et dans l'interface,
  habitudes acceptées proposées à l'heure en mode actif, coach en direct via Postgame.

## Décisions

| # | Date | Décision | Pourquoi |
|---|---|---|---|
| D1 | 2026-10-13 | Serveur de modèles : **llama-server** (binaire officiel Windows **Vulkan**, `b11583` figée), `--offline --no-webui --host 127.0.0.1` | Seule voie officielle pour la RX 6750 XT sous Windows ; pas de couche Ollama / LM Studio |
| D2 | 2026-10-13 | Candidats : Qwen3.5 9B, Gemma 4 12B, Ministral 3 14B (principal) ; Qwen3.5 4B, Gemma 4 E4B (routage) ; Gemma 4 26B-A4B en option | Les plus récents de 8 à 14 G, multimodaux, en GGUF |
| D3 | 2026-10-13 | ROCm mesuré en option seulement | gfx1031 non pris en charge officiellement sous Windows |
| D4 | 2026-10-13 | Transcription : **Parakeet TDT 0.6B v3 via onnx-asr** (dans le processus, CPU) ; faster-whisper en repli | Mesuré en J0 sur le poste de dev : 14 % d'erreurs contre 32 % (Whisper base), 250 ms ; onnx-asr évite de recharger le modèle à chaque phrase |
| D5 | 2026-10-13 | Voix : Piper (siwis) par défaut ; Kokoro si l'oreille et la latence le permettent | Kokoro 1,6 s sur le portable, à revoir sur le 5800X |
| D6 | 2026-10-13 | Mot de réveil : openWakeWord « hey jarvis » + **second étage** : si le score est « possible » (0,15 à 0,5), « Jarvis » est vérifié par la transcription des 1,6 dernières secondes | Aucun modèle « Jarvis » seul n'existe ; le modèle anglais rate la prononciation française. Modèle personnalisé prévu en J16 |
| D7 | 2026-10-13 | Garde réseau par crochet d'audit Python ; liste noire des fournisseurs d'IA ; téléchargements vérifiés par SHA-256 | Règle absolue SEC-04 |
| D8 | 2026-10-13 | Budget de latence : fin de parole 400 ms + transcription + 1re phrase du modèle + 1re phrase de voix | Voir `decision.py` et `banc.py` |
| D9 | 2026-10-13 | **Contexte fixe en cache** : consignes et outils strictement identiques en tête de requête ; date, mode jeu et souvenirs placés dans le message de Mathieu ; préchauffage au démarrage | PERF-06 : 6 500 jetons de contexte fixe ne sont traités qu'une fois (mesuré : 26 jetons traités à la 2e requête) |
| D10 | 2026-10-13 | **Deux emplacements** llama-server (`-np 2`, contexte doublé) | Une requête annexe (souvenirs, suggestions, vision) évinçait sinon le contexte fixe : plusieurs secondes perdues à la question suivante |
| D11 | 2026-10-13 | **Chemin rapide** : volume, musique, minuteur, heure, lancer/fermer une application connue, routines reconnus sans le modèle, mais exécutés via permissions + journal + vérification | PERF-02 et fiabilité : le petit modèle de test réglait le volume au lieu d'un minuteur |
| D12 | 2026-10-13 | **Réflexion à la demande** (`enable_thinking` par requête) pour les demandes complexes, annoncée à l'oral ; jamais en jeu | Intelligence là où elle compte, rapidité ailleurs |
| D13 | 2026-10-13 | Décodage spéculatif (brouillon Qwen3.5 0.8B) et cache KV q8_0 **activés par défaut, provisoires** ; repli automatique si llama-server les refuse | Extensions §2.2 ; gain à confirmer par le banc (≥ 20 % exigé) |
| D14 | 2026-10-13 | Garde anti-boucle : un même appel d'outil (mêmes arguments) jamais exécuté deux fois par tour | Le petit modèle fermait des applications en boucle |
| D15 | 2026-10-13 | Souvenirs automatiques (source « déduit de la conversation »), jamais à partir d'un contenu lu ni en jeu | « Un assistant qui connaît Mathieu » sans qu'il ait à tout dicter, transparence MEM-03 |
| D16 | 2026-10-13 | Accès distant par **`tailscale serve`** (HTTPS privé) ; le serveur n'écoute que sur 127.0.0.1 | SEC-06/11 ; le micro du navigateur exige HTTPS |
| D17 | 2026-10-13 | Notifications du téléphone par la connexion WebSocket directe (pas de Web Push) | Le Web Push passe par les serveurs de Google ; l'appli Android (J13) gardera la connexion en arrière-plan |
| D18 | 2026-10-13 | Interface compilée (`web/dist`) commitée | Pas besoin de Node sur le PC de jeu |
| D20 | 2026-10-13 | **Postgame : Jarvis lit les mesures locales et rédige lui-même les débriefs** ; l'appel à `/api/parties/{id}/debrief` est interdit dans le code | Postgame fait rédiger ses débriefs par Gemini : les déclencher depuis Jarvis ferait sortir des données à cause de Jarvis (règle absolue). Client aligné sur la vraie API (port 8765), vérifié contre le serveur de démonstration |
| D21 | 2026-10-13 | **IA-03 : pas d'entraînement LoRA ; personnalisation par les consignes et la mémoire** (exemples réels de Mathieu tirés du journal, ajoutés aux consignes fixes chaque jour) | Vérifié en premier comme demandé : l'outil d'entraînement de llama.cpp est expérimental (réglage complet FP32, 24 Go pour 1 G de paramètres) et absent des binaires Windows ; ROCm ne gère pas officiellement la RX 6750 XT sous Windows ; la piste LoRA Vulkan (fork qvac) reste à surveiller |
| D22 | 2026-10-13 | Souvenirs déduits et habitudes **proposés avant d'être retenus** (IA-04) ; un refus n'est jamais reproposé | Transparence et contrôle de Mathieu sur ce que Jarvis apprend |
| D19 | 2026-10-13 | Transcription anticipée dès 200 ms de silence | Masque le temps de transcription ; gain non mesurable sur le portable (bruit ±600 ms), à confirmer au banc |

## Valeurs provisoires (en attendant le PC de jeu)

| Brique | Valeur provisoire | Où la changer |
|---|---|---|
| Modèle principal | Qwen3.5 9B Q4_K_M + vision | `jarvis.toml` `[llm] principal` |
| Modèle rapide | le même (un seul modèle en VRAM) | `[llm] rapide` |
| Mode jeu | Qwen3.5 4B sur CPU | `[llm] mode_jeu` |
| Décodage spéculatif | brouillon Qwen3.5 0.8B | `[llm] speculatif` (aucun / brouillon / mtp / ngram) |
| Cache KV | q8_0 | `[llm] cache_kv` |
| Contexte | 16 384 jetons par emplacement | `[llm] contexte` |
| Transcription | Parakeet v3 int8, 4 fils | `[voix] stt`, `fils_stt` |
| Voix | Piper siwis | `[voix] tts` |
| Fin de parole | 400 ms ; anticipation 200 ms | `[voix] fin_de_parole_ms`, `anticipation_ms` |
| Mot de réveil | seuils 0,5 / 0,15 | `[voix] seuil_reveil`, `seuil_reveil_bas` |
| Interruption | par « Jarvis » (sans casque) | `[voix] interruption = "vad"` avec un casque |

## Points ouverts

- **Batterie de commandes** : 200 commandes provisoires écrites par Claude ; la liste réelle de
  Mathieu doit les compléter ou les remplacer (IA-01).
- **Coach en direct** : suppose une route `/api/{cs2|lol}/live` de Postgame ; si elle n'existe
  pas encore, l'outil le dit honnêtement.
- **Mémoire du POCO M7 Pro** (8 ou 12 Go) : décide si le mot de réveil reste actif en continu.
- **Wikipédia** refuse les requêtes Python depuis le poste de dev (403) : à vérifier au PC.
