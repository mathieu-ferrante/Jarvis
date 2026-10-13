# Jarvis — cahier des charges

*Assistant personnel vocal, le plus puissant possible, 100 % local.*
*Version 1.1 du 2026-10-13. Complète `BRIEF.md`.*

> **Pour lancer le projet dans une nouvelle conversation :** « Lis `CAHIER_DES_CHARGES.md`
> et mène le projet de bout en bout. » Le mode de travail (autonomie) est dans `CLAUDE.md`.

---

## 1. Contexte

Mathieu veut un véritable Jarvis : un assistant auquel il parle, qui agit sur son PC et sur
tout ce qu'il utilise, qui se souvient de lui et qui prend des initiatives. Il le veut **le
plus puissant possible**, avec une contrainte absolue : **tout reste en local, aucune
information ne sort du PC à cause de Jarvis**.

Projet personnel, non lié au travail. Projet frère : **Postgame**, un coach de jeux
(CS2, LoL, TFT, Geometry Dash) développé dans un autre dépôt (`Projetperso/Postgame`), que
Jarvis interrogera par son API locale.

## 2. Objectifs

1. **Parler naturellement** à son PC, en français, et être compris du premier coup.
2. **Déléguer de vraies tâches**, y compris en plusieurs étapes, et les voir exécutées.
3. **Un assistant qui connaît Mathieu** : ses projets, ses habitudes, ses préférences.
4. **Zéro fuite** : ni la voix, ni l'écran, ni la mémoire, ni les fichiers ne partent chez
   un fournisseur d'IA.

**Critère de réussite global :** au bout d'un mois, Mathieu utilise Jarvis plusieurs fois
par jour, sans y penser, pour des choses qu'il faisait avant à la main, et n'a jamais eu à
se demander où partaient ses données.

## 3. Le matériel cible

PC de jeu de Mathieu, sur lequel Jarvis tourne :

| Composant | Modèle | Conséquence |
|---|---|---|
| CPU | Ryzen 7 5800X (8 c / 16 t) | Transcription vocale et voix de synthèse possibles sur CPU |
| GPU | **AMD Radeon RX 6750 XT, 12 Go VRAM** (RDNA2, gfx1031) | Pas de CUDA. Inférence via **Vulkan** (llama.cpp). Modèle d'environ 8 à 14 milliards de paramètres en 4 bits |
| RAM | 32 Go DDR4 3200 | Possibilité de décharger une partie d'un modèle plus gros en RAM, au prix de la vitesse |
| Stockage | NVMe 1 To + NVMe 512 Go + HDD 4 To | Modèles sur NVMe ; archives et sauvegardes de la mémoire sur HDD |

**Partage du GPU avec les jeux** : quand Mathieu joue, le GPU est occupé. Jarvis doit le
détecter et passer en mode léger (modèle plus petit, ou sur CPU, ou modèle déchargé de la
VRAM), sans gêner le jeu.

**Le poste de développement n'est pas le PC de jeu** : c'est un poste Windows d'entreprise
sans GPU de jeu. Tout ce qui dépend du matériel (GPU, micro, haut-parleurs, latence) se
valide sur le PC de jeu.

## 4. Exigences fonctionnelles

### 4.1 Voix

| ID | Exigence |
|---|---|
| VOX-01 | **Mot de réveil « Jarvis »**, détecté en local, en permanence, à faible coût CPU. Aussi : raccourci clavier et bouton « appuyer pour parler ». |
| VOX-02 | **Transcription en français**, locale, robuste au bruit d'un PC de jeu et à l'accent naturel. |
| VOX-03 | **Voix de synthèse** française, naturelle, locale ; la réponse commence à être prononcée avant d'être entièrement générée (diffusion phrase par phrase). |
| VOX-04 | **Interruption** : Mathieu peut couper la parole à Jarvis, qui s'arrête immédiatement et écoute. |
| VOX-05 | **Conversation continue** : après une réponse, Jarvis reste à l'écoute quelques secondes sans nouveau mot de réveil. |
| VOX-06 | Mode texte équivalent (même cerveau, mêmes outils), sur PC et téléphone. |
| VOX-07 | Silence en jeu : pendant une partie, Jarvis ne parle que si on lui parle (sauf alerte demandée). |

### 4.2 Cerveau

| ID | Exigence |
|---|---|
| BRN-01 | **Modèle de langage local**, choisi au lancement du projet pour : qualité en français, fiabilité de l'appel d'outils, vitesse sur la RX 6750 XT. Comparatif chiffré obligatoire (J0). |
| BRN-02 | **Routage** : un modèle rapide pour les commandes simples (« baisse le son ») ; le modèle le plus capable pour le raisonnement et les tâches en plusieurs étapes. |
| BRN-03 | **Agent** : planifie, appelle des outils, lit les résultats, corrige, et rend compte. Les tâches longues tournent en arrière-plan et notifient à la fin. |
| BRN-04 | **Vérification** : après une action, Jarvis vérifie qu'elle a eu l'effet attendu avant d'annoncer qu'elle est faite. |
| BRN-05 | **Honnêteté** : s'il ne sait pas ou n'a pas pu faire, il le dit. Jamais de résultat inventé. |
| BRN-06 | **Vision** : modèle de vision local pour comprendre une capture d'écran ou une image (« qu'est-ce qui cloche sur mon écran ? »). |

### 4.3 Outils (les « mains »)

Chaque outil est un **module** : nom, description, paramètres, niveau de permission. Ajouter
un outil ne demande pas de toucher au cœur.

| ID | Domaine | Exemples d'actions |
|---|---|---|
| OUT-SYS | **Système Windows** | Lancer / fermer une appli ou un jeu, fenêtres, volume, sortie audio, luminosité, veille, état du PC (CPU, GPU, températures, disque) |
| OUT-FIC | **Fichiers** | Chercher (par nom et par contenu), ouvrir, ranger, renommer, résumer un document, convertir |
| OUT-WEB | **Web** | Recherche, lecture de pages, résumé ; automatisation du navigateur. Les requêtes sortent vers les sites consultés, jamais vers un fournisseur d'IA |
| OUT-CODE | **Exécution de code** | Scripts Python / PowerShell dans un bac à sable, pour calculer, transformer, automatiser |
| OUT-MED | **Médias** | Spotify / lecteur local : lecture, pause, recherche, playlists ; vidéos |
| OUT-COM | **Communication** | Mail et agenda (lire, résumer, rédiger, créer un évènement), Discord (lire, résumer, poster) |
| OUT-MAI | **Maison connectée** | Si Mathieu en a ou en ajoute : via Home Assistant en local |
| OUT-ROU | **Routines** | Enchaînements nommés (« mode jeu » : ferme le superflu, lance Discord et Steam, met la playlist) |
| OUT-REM | **Rappels et minuteurs** | « Rappelle-moi dans 20 min », « tous les lundis » |
| OUT-JEU | **Coach de jeux** | Interroge l'API locale de Postgame : dernière session, mesures, progression, débrief |
| OUT-DEV | **Projets perso** | État d'un dépôt git, lancer les tests, résumer les derniers changements |

### 4.4 Mémoire

| ID | Exigence |
|---|---|
| MEM-01 | **Mémoire à long terme** des faits sur Mathieu (préférences, projets, habitudes, personnes), avec date et source. |
| MEM-02 | **Recherche sémantique locale** dans la mémoire et dans les documents que Mathieu choisit d'indexer. |
| MEM-03 | **Transparence** : Mathieu peut demander ce que Jarvis sait sur un sujet, corriger, et faire oublier. |
| MEM-04 | **Historique des conversations** consultable et cherchable. |
| MEM-05 | Sauvegarde automatique et chiffrée de la mémoire sur le disque de sauvegarde. |

### 4.5 Initiative

| ID | Exigence |
|---|---|
| INI-01 | **Briefing du matin** (déclenché à la première activité du jour) : agenda, mails importants, rappels, météo, veille. |
| INI-02 | **Suivi des tâches longues** : notification à la fin, avec le résultat. |
| INI-03 | **Suggestions** discrètes, désactivables, basées sur la mémoire (« tu m'avais demandé de te rappeler… »). |

### 4.6 Accès

| ID | Exigence |
|---|---|
| ACC-01 | **PC** : présence discrète (icône de zone de notification, fenêtre flottante appelable). |
| ACC-02 | **Téléphone** : interface installable (PWA) avec appui pour parler, texte, notifications. Pas d'appli native (Gradle bloqué sur le poste de développement). |
| ACC-03 | **Hors de chez soi** : accès par un réseau privé entre les appareils de Mathieu (Tailscale). Aucun port ouvert sur Internet. |
| ACC-04 | **Mac** : client de l'interface web. |

## 5. Sécurité — exigences bloquantes

Jarvis a beaucoup de pouvoir : la sécurité n'est pas un lot de fin, elle est dans le socle.

| ID | Exigence |
|---|---|
| SEC-01 | **Niveaux de permission** par outil : *lecture* (libre), *action réversible* (libre, annoncée), *action irréversible ou sortante* — envoyer un message, supprimer, publier, acheter, modifier un réglage système — **toujours confirmée** par Mathieu, à la voix ou au clic, avec le détail de l'action. |
| SEC-02 | **Injection de consignes** : le contenu lu par Jarvis (page web, mail, fichier, message Discord) est traité comme une donnée, jamais comme une instruction. Une action proposée à la suite d'un contenu lu exige une confirmation. |
| SEC-03 | **Journal** de toutes les actions exécutées (quoi, quand, à la suite de quelle demande), consultable. |
| SEC-04 | **Pas de fuite** : aucun appel à une API d'IA distante. Liste blanche des sorties réseau par outil. Un test automatisé vérifie qu'aucun module du cœur (voix, cerveau, mémoire) n'ouvre de connexion sortante. |
| SEC-05 | **Secrets** (jetons mail, Discord, Spotify…) stockés chiffrés, jamais dans le dépôt, jamais envoyés au modèle. |
| SEC-06 | **Accès distant** limité aux appareils de Mathieu (Tailscale) et protégé par une authentification. |
| SEC-07 | **Bouton d'arrêt** : une commande vocale et un raccourci coupent immédiatement toute action en cours. |

## 6. Exigences non fonctionnelles

| ID | Exigence |
|---|---|
| NF-01 | **Latence** : début de la réponse parlée en moins de 1,5 s pour une question simple (fin de parole → premier son), mesurée sur le PC de jeu. |
| NF-02 | **Fiabilité de l'appel d'outils** : sur une batterie de 50 commandes types, au moins 90 % exécutées correctement du premier coup. Batterie versionnée et rejouée à chaque changement de modèle. |
| NF-03 | **Ressources** : au repos, moins de 5 % de CPU et VRAM libérée si nécessaire. Ne dégrade pas les performances en jeu. |
| NF-04 | **Coût** : 0 € de fonctionnement. Logiciels libres et modèles à poids ouverts. |
| NF-05 | **Démarrage** avec Windows, en moins de 30 s jusqu'à « prêt ». |
| NF-06 | **Langue** : français partout, interface, voix, documentation et commits. |

## 7. Architecture

```
┌───────────────────────────────── PC de jeu (Windows) ─────────────────────────────────┐
│                                                                                       │
│  Micro ─► Mot de réveil ─► Détection de fin de parole ─► Transcription ─┐             │
│                                                                         ▼             │
│                                          ┌──────────── Orchestrateur ────────────┐    │
│  Haut-parleurs ◄─ Voix de synthèse ◄─────┤  routage des modèles, agent, outils,  │    │
│                                          │  permissions, journal, tâches de fond │    │
│                                          └──┬─────────┬──────────┬───────────┬───┘    │
│                                             │         │          │           │        │
│                        Serveur de modèles locaux   Mémoire    Outils     API + WebSocket │
│                        (llama.cpp, Vulkan)         (vecteurs  (modules)     │        │
│                        texte + vision              + SQLite)                │        │
└─────────────────────────────────────────────────────────────────────────────┼────────┘
                                                                              │
                                                Interface web (PC, téléphone, Mac) via Tailscale
```

- **Langage du cœur** : Python 3.13 (écosystème IA, audio, automatisation Windows).
- **Modèles** : servis par llama.cpp (backend Vulkan), via une API compatible OpenAI en
  local, pour pouvoir changer de modèle sans toucher au code.
- **Voix** : mot de réveil (openWakeWord ou équivalent), détection d'activité vocale,
  transcription (whisper.cpp Vulkan ou faster-whisper CPU — à départager en J0), synthèse
  (Piper ou modèle plus expressif — à départager en J0).
- **Mémoire** : SQLite + index vectoriel local, modèle d'embeddings local.
- **Interface** : React + Vite + TypeScript, PWA.

Les choix marqués « à départager » sont tranchés **par la mesure** en J0, pas à l'intuition.

## 8. Hors périmètre

- Tout appel à une IA dans le cloud.
- Appli mobile native.
- Actions financières (paiement, virement, achat) : Jarvis peut préparer, jamais exécuter.
- Écoute ou enregistrement de tiers.

## 9. Plan par lots

| Lot | Contenu | Exigences | Fini quand |
|---|---|---|---|
| **J0 — Diagnostic et choix par la mesure** | Script de diagnostic à lancer sur le PC de jeu : GPU et Vulkan, débit de 3 modèles candidats, latence de transcription et de voix, micro. Comparatif chiffré | BRN-01, NF-01 | Les choix de modèles et de briques sont tranchés, chiffres à l'appui |
| **J1 — Boucle vocale** | Mot de réveil → transcription → modèle → voix, interruption, conversation continue | VOX-01 à 05 | Une question posée à voix haute reçoit une réponse parlée en moins de 1,5 s |
| **J2 — Cœur et sécurité** | Orchestrateur, système de modules d'outils, permissions, journal, arrêt d'urgence, test anti-fuite | BRN-03/04/05, SEC-01 à 07 | Un outil factice de chaque niveau de permission se comporte comme prévu |
| **J3 — Outils PC** | Système, fichiers, médias, routines, rappels, exécution de code | OUT-SYS, OUT-FIC, OUT-MED, OUT-ROU, OUT-REM, OUT-CODE | Batterie de 50 commandes ≥ 90 % |
| **J4 — Mémoire** | Faits, recherche sémantique, historique, oubli, sauvegarde | MEM-* | Jarvis se souvient d'une préférence d'une semaine sur l'autre et l'oublie sur demande |
| **J5 — Interface et téléphone** | Interface web, PWA, Tailscale, notifications | VOX-06, ACC-* | Utilisable depuis le téléphone hors de chez soi |
| **J6 — Web et vision** | Recherche, lecture de pages, navigateur, compréhension d'écran | OUT-WEB, BRN-06 | « Qu'est-ce qui cloche sur mon écran ? » donne une réponse juste |
| **J7 — Communication** | Mail, agenda, Discord | OUT-COM | Briefing et rédaction fonctionnent, envois toujours confirmés |
| **J8 — Initiative** | Briefing du matin, suggestions, suivi des tâches longues | INI-* | Le briefing tourne une semaine sans intervention |
| **J9 — Coach de jeux et projets** | Outils Postgame et projets perso ; mode jeu | OUT-JEU, OUT-DEV, VOX-07, NF-03 | « Comment était ma session DM ? » répond avec les vraies mesures |
| **J10 — Maison connectée** | Home Assistant, si équipement | OUT-MAI | Selon l'équipement |

Chaque lot se termine par : tests verts, validation sur le PC de jeu, commit, mise à jour du
README.

## 10. Risques

| Risque | Conséquence | Comment le tester tôt |
|---|---|---|
| Le support Vulkan / AMD est lent ou instable | Jarvis trop lent | J0 mesure le débit réel avant toute autre ligne de code |
| Un modèle de 12 Go appelle mal les outils | Jarvis peu fiable | Batterie de 50 commandes dès J2, choix du modèle par la mesure, outils simples et bien décrits |
| Latence vocale trop élevée | On arrête de l'utiliser | Mesurée en J0 et J1 ; diffusion phrase par phrase |
| Conflit avec les jeux pour le GPU | Jeux saccadés ou Jarvis indisponible | Mode jeu (J9) ; tester pendant une partie de CS2 |
| Faux déclenchements du mot de réveil | Agaçant | Mesurer le taux sur une soirée de jeu en J1 |
| Action dangereuse mal comprise | Dommage réel | Permissions et confirmation dès J2, avant tout vrai outil |
| Injection de consignes via un mail ou une page | Action non voulue | Tests d'injection dans la batterie dès J6–J7 |

## 11. Ce que Mathieu fournit

- Les exécutions du script de diagnostic sur le PC de jeu (J0) et les validations à chaque lot.
- Les accès qu'il choisit de brancher (mail, agenda, Discord, Spotify), configurés par lui.
- La liste de ses commandes du quotidien, pour construire la batterie de 50 commandes.
