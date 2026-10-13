# Jarvis — brief de lancement

À faire lire au début de la conversation dédiée à Jarvis. Rédigé le 2026-10-13 à la fin de
la conversation où le projet a été choisi.

## L'idée

Un véritable assistant personnel à la Jarvis, **le plus puissant possible**, qui tourne
**entièrement en local** sur le PC de jeu de Mathieu. Projet perso, pas lié au travail.

Projet frère : le **coach de jeux Postgame** (CS2, LoL, TFT, Geometry Dash), développé dans un autre
dépôt et une autre conversation (`Projetperso/Postgame`, voir son `CAHIER_DES_CHARGES.md`). Jarvis devra
pouvoir l'interroger comme un outil (« Jarvis, comment était ma session DM ? »). On prévoit
donc dès le départ un système de compétences branchables (un outil = un module, interface
stable).

## Contrainte non négociable

**Aucune information ne sort du PC à cause de Jarvis.** Pas d'API d'IA dans le cloud pour
Jarvis : modèle de langage, transcription, voix, mémoire, tout tourne localement. Jarvis
peut aller *chercher* de l'information (web, mail, agenda) si on le branche, mais rien de
ce qu'il voit, entend ou retient n'est envoyé à un fournisseur d'IA.

(Les 15 € de crédit Gemini de Mathieu ne servent donc pas à Jarvis. Ils peuvent servir au
coach de jeux, dont les données — statistiques de parties — ne sont pas sensibles.)

## Le matériel (PC de jeu, là où Jarvis tournera)

- CPU Ryzen 7 5800X (8 cœurs / 16 threads)
- GPU **AMD Radeon RX 6750 XT, 12 Go de VRAM** (RDNA2, gfx1031)
- 32 Go DDR4 3200 MHz
- SSD NVMe 1 To + SSD NVMe 512 Go + HDD 4 To
- Alimentation Corsair 750 W Gold

**Important :** le poste sur lequel on code avec Claude n'est *pas* le PC de jeu. C'est un
poste Windows d'entreprise (Gradle bloqué, pas de Steam, pas de GPU de jeu). Tout ce qui
dépend du matériel (GPU, micro, latence) se teste sur le PC de jeu. Prévoir dès le départ un
script de diagnostic à lancer là-bas, qui remonte ce qui marche.

## Ce que ça implique techniquement (à vérifier en premier)

- **Carte AMD, pas NVIDIA.** Beaucoup d'outils d'IA locale supposent CUDA. Sur une RX 6750 XT
  sous Windows, la voie la plus sûre est **llama.cpp avec le backend Vulkan** (directement, ou
  via LM Studio / Ollama si leur support Vulkan est en place). Le support ROCm Windows de
  cette carte (gfx1031) n'est pas officiel : à vérifier, ne pas le supposer.
- **12 Go de VRAM** : un modèle d'environ 8 à 14 milliards de paramètres quantifié en 4 bits
  tient en VRAM avec un contexte raisonnable. Choisir un modèle récent, bon en français et
  en appel d'outils (à comparer au moment du lancement, le paysage bouge vite).
- **Honnêteté sur la puissance** : un modèle local de cette taille est très en dessous des
  grands modèles cloud pour les tâches longues et complexes. « Le plus puissant possible »
  passe donc par l'architecture : outils fiables et bien décrits, découpage des tâches,
  vérification des résultats, mémoire bien structurée, et routage (petit modèle rapide pour
  les commandes simples, plus gros pour le raisonnement).
- **Transcription** : faster-whisper est CUDA-only en GPU ; sur cette machine, whisper.cpp
  (Vulkan) ou faster-whisper sur CPU (le 5800X suffit pour un modèle small/medium en int8).
- **Voix de synthèse** : locale (Piper pour la latence, ou un modèle plus expressif si la
  latence le permet). Français de bonne qualité indispensable.
- **Mot de réveil** : « Jarvis », local (openWakeWord ou équivalent).

## Les capacités visées

| Capacité | Description |
|---|---|
| Voix | Réveil par « Jarvis », français, réponse rapide, **interruption possible** pendant qu'il parle |
| Cerveau | Planifie des tâches en plusieurs étapes, choisit ses outils, vérifie ce qu'il fait |
| Mains | Applis, jeux, fichiers, fenêtres, son, médias, navigateur, exécution de code, automatisations Windows |
| Yeux | Comprend l'écran (capture + modèle de vision local) |
| Mémoire | Se souvient de Mathieu, de ses projets et préférences, d'une session à l'autre (recherche sémantique locale) |
| Initiative | Briefing du matin, rappels, routines, suivi de tâches longues avec notification |
| Partout | Interface PC + téléphone (PWA, appui pour parler), accès hors de chez soi par un tunnel privé (Tailscale) — le trafic reste entre les appareils de Mathieu |
| Tout piloter | Mathieu veut qu'il puisse « tout » piloter : mail, agenda, fichiers, médias, Discord, maison connectée… en respectant la règle du local |
| Coach de jeux | Interroge le projet frère via son API locale |

## Sécurité (indispensable vu les pouvoirs donnés)

- Permissions graduées : lecture libre, actions réversibles sans confirmation, actions
  irréversibles ou sortantes (envoyer un message, supprimer, payer) **toujours confirmées**.
- Journal de toutes les actions exécutées, consultable.
- Un contenu lu par Jarvis (page web, mail, fichier) n'est jamais une instruction : protection
  contre l'injection de consignes.
- Le micro n'est traité qu'en local, rien n'est envoyé nulle part.

## Proposition de démarrage

1. Cadrage court (périmètre de la v1, critères de réussite), en s'appuyant sur ce brief.
2. Script de diagnostic à lancer sur le PC de jeu : GPU détecté, Vulkan, vitesse d'un modèle
   local, micro, transcription, voix. **Rien d'autre avant d'avoir ces chiffres.**
3. Boucle vocale minimale de bout en bout : « Jarvis » → question → réponse parlée.
4. Outils PC, puis mémoire, puis initiative, puis téléphone.

## Contexte utile sur Mathieu

- Projets perso déjà faits : Frigo Zéro (anti-gaspi, Expo), Sous-Contrôle (dépenses,
  Kotlin), Phalanx (auto-battler coop Godot), portfolio 3D (three.js), OnlyBrief (veille
  quotidienne IA / tech / Counter-Strike, Python + Gemini).
- Joue à CS2 (Premier, beaucoup de DM et de modes d'entraînement), LoL, TFT, Geometry Dash.
- Écrit en français ; documentation et commits en français.
