# Jarvis

Assistant personnel vocal, le plus puissant possible, **100 % local** : aucune information ne
sort du PC à cause de Jarvis, aucun appel à une IA dans le cloud.

- Cahier des charges : [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md), [extensions](CAHIER_DES_CHARGES_EXTENSIONS.md), [BRIEF.md](BRIEF.md)
- Avancement et décisions : [PLAN.md](PLAN.md)
- À lancer sur le PC de jeu : [A_VALIDER.md](A_VALIDER.md)

## État

Lots J0 à J18 **codés et testés sur le poste de développement** (207 tests automatisés) ;
**aucun n'a encore été validé sur le PC de jeu** : performances, voix et modèles définitifs
se mesurent là-bas (voir A_VALIDER.md). L'appli Android n'a jamais été compilée et l'agent
Mac n'a jamais tourné sur un Mac.

## Ce que fait Jarvis

- **Voix** : « Jarvis… » (ou Ctrl+Alt+J), réponse parlée dès la première phrase, interruption,
  conversation continue, confirmation à la voix. Transcription Parakeet v3, voix Piper, tout
  sur CPU.
- **Cerveau** : modèle local (llama.cpp Vulkan) choisi par le diagnostic ; agent qui enchaîne
  les outils, vérifie ses actions et dit honnêtement quand il échoue ; réflexion approfondie
  seulement quand elle sert ; commandes fréquentes traitées sans le modèle.
- **Mains** : ~60 outils — applications, fenêtres, volume, sortie audio, luminosité, fichiers,
  musique et Spotify, rappels, routines, Python en bac à sable, web, vision de l'écran, mail,
  agenda, Discord, Postgame, dépôts git, Home Assistant.
- **Mémoire** : se souvient de Mathieu (faits datés et sourcés, appris aussi des conversations),
  recherche par le sens, historique, oubli sur demande, sauvegarde chiffrée.
- **Initiative** : briefing du matin, suggestions (silencieux / discret / actif), rappels,
  tâches de fond notifiées, coach en direct pendant les parties (via Postgame).
- **Partout** : interface web (PWA), appli Android native et agent macOS, via Tailscale ;
  notifications sur l'appareil utilisé, conversation commune, outils de chaque appareil
  pilotables depuis les autres, rappels à un lieu ou à la fin d'une partie.
- **Apprend** : mot de réveil entraîné sur la voix de Mathieu, empreinte vocale, habitudes et
  souvenirs proposés avant d'être retenus, tâches de fond reprises après redémarrage.
- **Mode jeu** : détecte la partie, libère la VRAM, passe en silence.

## Sécurité

- Lecture libre, actions réversibles annoncées, actions irréversibles ou sortantes **toujours
  confirmées** (voix, clic, empreinte sur Android) ; journal de toutes les actions.
- Le contenu lu (mail, page, fichier, écran) est une donnée, jamais une instruction.
- Garde réseau : liste blanche des sorties par outil, fournisseurs d'IA bloqués, test
  anti-fuite automatisé ; serveur sur 127.0.0.1 uniquement, accès distant par Tailscale.
- Secrets chiffrés (DPAPI), jamais dans le dépôt ni montrés au modèle ; arrêt d'urgence
  Ctrl+Alt+K ou « Jarvis, stop ».

## Installation (PC de jeu)

```
diagnostic.cmd --donnees D:\Jarvis      (une fois : choisit les modèles par la mesure)
installer.cmd -Demarrage -Tailscale
jarvis.cmd --fenetre
```

Commandes utiles : `python -m jarvis outils` (liste des outils), `python -m jarvis banc`
(performance et batterie de commandes), `python -m jarvis secrets definir <nom>`,
`python -m jarvis sauvegarde --cle`, `python -m jarvis appareils`,
`python -m jarvis enroler-voix`, `python -m jarvis entrainer-reveil`,
`python -m jarvis evaluer <modèle>`,
`python -m jarvis verifier` (contrôle de l'installation, rapport à renvoyer).

Configuration : `%LOCALAPPDATA%\Jarvis\jarvis.toml` (créé au premier lancement, commenté).

## Développement

Poste de développement (sans GPU de jeu) :

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[voix,app,dev]"
.venv\Scripts\python -m pytest                 # tests rapides
.venv\Scripts\python -m pytest -m lent         # bout en bout avec les vrais moteurs
.venv\Scripts\python -m jarvis diagnostic --rapide --sans-micro
```

Interface : `cd web && npm install && npm run build` (le résultat `web/dist` est commité).

## Structure

```
src/jarvis/
  application.py        assemblage et démarrage
  agent/                orchestrateur, consignes, routage, chemin rapide, tâches de fond
  llm/                  serveur llama.cpp et client (diffusion, outils, réflexion)
  voix/                 boucle vocale, moteurs (réveil, VAD, Parakeet, Piper), audio
  outils/               un module par domaine (système, fichiers, web, communication…)
  memoire/              faits, recherche, historique, souvenirs automatiques, sauvegarde
  securite/             garde réseau, coffre, journal, permissions
  serveur/              API FastAPI + WebSocket, appareils appairés
  jeu.py, initiative.py mode jeu ; briefing et suggestions
  banc.py               banc de performance et batterie de commandes
  diagnostic/           lot J0
  mac/                  agent macOS (barre des menus, outils, secours local)
android/                application Android (Kotlin, Compose)
web/                    interface PWA (React + TypeScript)
tests/                  tests automatisés
```
