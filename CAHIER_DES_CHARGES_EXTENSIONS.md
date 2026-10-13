# Jarvis — extensions « niveau maximum » et multi-appareils

*Version 1.1 du 2026-10-13. Complète `CAHIER_DES_CHARGES.md` (v1.1) sans le remplacer.*
*À traiter après le lot J10 ; les lots J11 à J18 viennent à la suite.*

---

## 1. Objectif

Pousser Jarvis au meilleur niveau possible **sur le matériel existant**, sur **trois
appareils** : le PC de jeu (le cerveau), le Mac et le téléphone. Un seul Jarvis, avec une
mémoire et un journal communs, qui répond sur l'appareil où se trouve Mathieu.

**Règle absolue inchangée** : aucune information ne sort des appareils de Mathieu à cause de
Jarvis. Les échanges entre appareils passent uniquement par Tailscale.

## 2. PRIORITÉ N° 1 : performance et optimisation au maximum

**Principe directeur** : sur un matériel limité, la performance *est* l'intelligence perçue.
Un Jarvis qui répond en 0,8 s avec un modèle bien optimisé vaut mieux qu'un Jarvis qui répond
en 4 s avec un modèle à peine meilleur. **Chaque lot doit respecter les budgets ci-dessous ;
une régression de performance bloque un lot au même titre qu'un test rouge.**

### 2.1 Budgets mesurés (objectifs bloquants)

| ID | Mesure | Objectif | Mesuré sur |
|---|---|---|---|
| PERF-01 | Fin de parole → premier son, question simple, au PC | **< 1,0 s** (cible), < 1,5 s (maximum, NF-01) | PC de jeu |
| PERF-02 | Fin de parole → action exécutée (« baisse le son ») | **< 1,2 s** | PC de jeu |
| PERF-03 | Fin de parole → premier son depuis le téléphone, Wi-Fi | < 1,8 s | POCO + PC |
| PERF-04 | Idem en 4G / 5G via Tailscale | < 3,0 s | POCO + PC |
| PERF-05 | Génération du modèle principal | ≥ 40 jetons/s | PC de jeu |
| PERF-06 | Traitement du contexte fixe (consignes + outils) | 0 ms après la 1re requête (cache) | PC de jeu |
| PERF-07 | CPU au repos (mot de réveil compris), PC | < 2 % | PC de jeu |
| PERF-08 | Impact en jeu (mode jeu actif) | < 2 % d'images par seconde perdues dans CS2 | PC de jeu |
| PERF-09 | Démarrage jusqu'à « prêt » | < 15 s (NF-05 exigeait 30 s) | PC de jeu |
| PERF-10 | Passage en mode jeu (VRAM libérée) | < 3 s | PC de jeu |
| PERF-11 | Batterie du téléphone, Jarvis en arrière-plan | < 4 % par jour | POCO |
| PERF-12 | Agent macOS au repos | < 1 % CPU, < 200 Mo | Mac |
| PERF-13 | Recherche en mémoire (10 000 souvenirs) | < 50 ms | PC de jeu |

### 2.2 Techniques imposées

**Modèle de langage (PC)**
- Choix du modèle et de la quantification **par la mesure** (diagnostic J0, rejoué à chaque
  nouvelle version de llama.cpp ou de modèle).
- **Cache du contexte** : consignes et définitions d'outils strictement fixes en tête de
  requête, partie variable à la fin ; réutilisation du cache de llama-server entre requêtes.
- **Décodage spéculatif** (petit modèle brouillon ou n-grammes) si le gain mesuré est ≥ 20 %.
- **Flash attention** et **cache KV quantifié** (q8_0) si la qualité de la batterie ne baisse pas.
- **Modèle gardé chaud** en VRAM hors mode jeu ; préchauffage au démarrage.
- **Routage** : commandes simples traitées par le chemin le plus court (modèle rapide, ou
  reconnaissance directe des commandes très fréquentes sans passer par le modèle).
- **Réflexion approfondie** activée seulement pour les demandes qui la méritent.
- Contexte borné : historique résumé au-delà de N tours, résultats d'outils tronqués.

**Voix**
- Diffusion de bout en bout : la synthèse commence dès la première phrase, la phrase n+1 est
  synthétisée pendant que la phrase n est jouée.
- **Transcription en flux** : la transcription commence pendant que Mathieu parle (pas
  seulement après la fin de parole).
- Détection de fin de parole réglée par la mesure (compromis coupure / latence).
- Moteurs vocaux sur CPU (le GPU reste au modèle et au jeu), fils de calcul réglés et affinité
  processeur choisie pour ne pas gêner le jeu.
- Réponses préenregistrées pour les accusés de réception fréquents (« c'est fait »).

**Système**
- Priorité de processus basse pour Jarvis en jeu, normale sinon.
- Chargement paresseux de tout ce qui n'est pas utilisé au démarrage.
- Pas de Python lourd dans le chemin critique : tout ce qui est sur la boucle vocale est profilé.

**Réseau et appareils**
- Audio du téléphone compressé (Opus), envoyé en flux pendant la parole.
- Détection de parole sur le téléphone : seul le son utile part vers le PC.
- Connexion persistante (WebSocket) via Tailscale, pas de reconnexion à chaque requête.

### 2.3 Mesure continue

- **Banc de performance automatisé** (`python -m jarvis banc`) qui mesure PERF-01 à 13, écrit
  un rapport daté et le compare au précédent.
- **Test de non-régression** : tout changement qui dégrade un budget de plus de 10 % est
  signalé et doit être justifié dans `PLAN.md`.
- **Tableau de bord** dans l'interface : latence par étape (transcription, modèle, voix),
  débit, VRAM, CPU, pour chaque échange.
- **Évaluation continue des modèles** : à chaque nouveau modèle ouvert prometteur, rejouer
  la batterie de commandes et le banc ; adopter seulement s'il fait mieux sur les deux.

## 3. Ce qui change par rapport au cahier des charges v1.1

| Point v1.1 | Évolution |
|---|---|
| NF-01 (1,5 s) | Cible abaissée à 1,0 s (PERF-01), 1,5 s reste le maximum. |
| NF-05 (30 s) | Cible abaissée à 15 s (PERF-09). |
| ACC-02 « pas d'appli native » | **Application Android native** ajoutée (TEL-*), compilée sur le PC de jeu. La PWA reste en secours. |
| ACC-04 « Mac : client web » | Mac client natif, pilotable, secours léger (MAC-*). |
| VOX-01 | Mot de réveil « Jarvis » entraîné sur la voix de Mathieu (VOX-10), aussi sur le téléphone. |

## 4. Matériel

| Appareil | Caractéristiques | Rôle |
|---|---|---|
| PC de jeu | Ryzen 5800X, RX 6750 XT 12 Go, 32 Go | **Cerveau** : modèles, mémoire, orchestrateur, journal |
| Mac | Apple M2, **8 Go** de mémoire unifiée | Client, pilotage macOS, secours léger (modèle de 3 à 4 milliards de paramètres au plus) |
| Téléphone | **POCO M7 Pro 5G** (Android, HyperOS, MediaTek Dimensity, 8 ou 12 Go à confirmer) | Interface mobile : voix (avec mot de réveil), texte, notifications, confirmations, contexte |

**Limites assumées** : le Mac 8 Go ne fait pas tourner de modèle plus capable que le PC ; pas
de répartition d'un modèle entre machines. Le téléphone ne fait pas tourner le cerveau.

## 5. Exigences fonctionnelles nouvelles

### 5.1 Mac

| ID | Exigence |
|---|---|
| MAC-01 | Agent macOS léger connecté au cœur via Tailscale, avec un jeton propre à l'appareil. |
| MAC-02 | Client vocal et texte : raccourci clavier, appuyer pour parler, icône dans la barre des menus. |
| MAC-03 | Pilotage du Mac : applications, volume, fichiers, Rappels, Calendrier, Notes, Mail (AppleScript / Shortcuts), capture d'écran pour la vision. |
| MAC-04 | Mode secours : PC injoignable → petit modèle local (llama.cpp Metal, chargé à la demande puis déchargé) pour les commandes simples ; Jarvis annonce le mode réduit. |
| MAC-05 | Outils du Mac dans le même registre, mêmes niveaux de permission (SEC-01). |

### 5.2 Téléphone (POCO M7 Pro 5G, Android)

| ID | Exigence |
|---|---|
| TEL-01 | **Application Android native (Kotlin)**, compilée sur le PC de jeu (Gradle est bloqué sur le poste de développement, pas sur le PC de jeu). Installation directe (APK), sans Play Store. PWA conservée en secours. |
| TEL-02 | **Mot de réveil « Jarvis » sur le téléphone** : modèle ONNX léger (ONNX Runtime Android) dans un service de premier plan (notification permanente, exigée par Android). Activable / désactivable, désactivé automatiquement sous un seuil de batterie. |
| TEL-03 | **Voix** : appui pour parler, widget, tuile des réglages rapides ; audio Opus envoyé en flux au PC. |
| TEL-04 | **Notifications sans Google** : connexion persistante au PC via Tailscale dans le service de l'application ; aucun contenu ne passe par Firebase. |
| TEL-05 | **Confirmations** d'actions irréversibles d'un tap, avec empreinte digitale (BiometricPrompt). |
| TEL-06 | **Contexte, avec accord explicite et désactivable** : position (rappels géolocalisés), batterie, déplacement. Rien n'est conservé au-delà du besoin. |
| TEL-07 | **Hors connexion** : dernière vue (rappels, agenda du jour) gardée, demandes mises en file. |
| TEL-08 | **Intégration HyperOS** : écran guidé pour autoriser le démarrage automatique, retirer les restrictions de batterie et verrouiller l'application dans les applications récentes (sinon HyperOS la tue). |

### 5.3 Multi-appareils

| ID | Exigence |
|---|---|
| MULTI-01 | Un seul cerveau sur le PC (orchestrateur, mémoire, journal) ; les autres sont clients et « mains ». |
| MULTI-02 | Présence : Jarvis sait quel appareil est actif (dernière interaction, verrouillage, en jeu) et répond sur celui-là. |
| MULTI-03 | Continuité d'une conversation d'un appareil à l'autre. |
| MULTI-04 | Outils inter-appareils : « envoie ce fichier sur mon téléphone », « ouvre ce lien sur mon PC », « fais sonner mon téléphone ». |
| MULTI-05 | Notifications sans doublon : appareil actif d'abord, autres ensuite si non lue. |
| MULTI-06 | Dégradation propre : PC injoignable → le Mac prend le relais en mode secours, le téléphone le signale. |

### 5.4 Voix au niveau maximum

| ID | Exigence |
|---|---|
| VOX-10 | Mot de réveil « Jarvis » personnalisé (enregistrements de Mathieu + prononciations françaises synthétiques), sur PC et téléphone. Objectif : > 95 % de détection, < 1 faux déclenchement par soirée de jeu. |
| VOX-11 | Identification du locuteur : actions sensibles refusées pour une autre voix. |
| VOX-12 | Voix plus expressive, seulement si PERF-01 reste tenu. |
| VOX-13 | Annulation d'écho pour interrompre Jarvis sans casque. |

### 5.5 Intelligence au niveau maximum

| ID | Exigence |
|---|---|
| IA-01 | Batterie de 200 commandes réelles, versionnée. Objectif : > 95 % du premier coup. |
| IA-02 | Planification des tâches longues : plan explicite, exécution par étapes, reprise après erreur, compte rendu. |
| IA-03 | Personnalisation (LoRA) d'un modèle ouvert sur les données locales de Mathieu ; faisabilité de l'entraînement sur AMD sous Windows **à vérifier en premier**. |
| IA-04 | Mémoire qui apprend les habitudes, proposées à Mathieu avant d'être retenues. |
| IA-05 | Évaluation continue des nouveaux modèles (batterie + banc de performance). |
| IA-06 | Agent qui voit et pilote l'écran, réservé aux cas non couverts par un outil, avec confirmation. |

### 5.6 Initiative au niveau maximum

| ID | Exigence |
|---|---|
| INI-10 | Proactivité réglable (silencieuse / discrète / active), suggestions journalisées. |
| INI-11 | Rappels selon le contexte : lieu, appareil, fin de partie. |
| INI-12 | Coach en direct pendant une partie, via Postgame, seulement sur demande (VOX-07). |

## 6. Sécurité — ajouts bloquants

| ID | Exigence |
|---|---|
| SEC-10 | Appairage de chaque appareil par code à usage unique affiché sur le PC ; jeton par appareil, révocable. |
| SEC-11 | Liste de contrôle Tailscale : seuls les appareils de Mathieu joignent Jarvis ; aucun port ouvert sur Internet. |
| SEC-12 | Permissions par appareil : actions irréversibles depuis le téléphone uniquement avec biométrie. |
| SEC-13 | Perte du téléphone : révocation immédiate depuis le PC ou le Mac. |
| SEC-14 | Le test anti-fuite (SEC-04) couvre l'agent macOS et l'application Android. |
| SEC-15 | APK signé avec une clé de Mathieu, gardée hors du dépôt. |

## 7. Architecture cible

```
   POCO M7 Pro (appli Android) ──┐   mot de réveil + détection de parole sur le téléphone,
                                  │   audio Opus en flux
                                  │  Tailscale (privé, chiffré, connexion persistante)
   Mac M2 8 Go (agent macOS) ─────┼──────────────► PC de jeu : CERVEAU
     └─ secours : petit modèle    │                 orchestrateur, llama.cpp Vulkan (cache,
        Metal à la demande        │                 spéculatif), voix CPU, mémoire, journal
                                  └─ notifications ◄─ bus d'évènements
```

## 8. Hors périmètre (confirmé)

- Créer ou entraîner une IA from scratch : hors de portée du matériel, et le résultat serait
  inférieur aux modèles ouverts. On personnalise (IA-03), on n'entraîne pas depuis zéro.
- Répartir un modèle entre le PC et le Mac.
- Faire tourner le cerveau sur le téléphone.
- Tout appel à une IA dans le cloud ; toute notification dont le contenu passe par Google.

## 9. Lots supplémentaires

**Règle commune** : chaque lot se termine par le banc de performance (2.3) ; aucun budget
PERF ne doit régresser.

| Lot | Contenu | Exigences | Fini quand | Durée estimée |
|---|---|---|---|---|
| **J11 — Optimisation du socle** | Banc de performance, cache du contexte, décodage spéculatif, transcription en flux, réglage de fin de parole, tableau de bord | PERF-01 à 10, 13 | PERF-01 < 1,0 s mesuré sur le PC de jeu | 3 à 4 semaines |
| **J12 — Socle multi-appareils** | Appairage, jetons, présence, routage des notifications | MULTI-01/02/05, SEC-10 à 13 | Un appareil appairé reçoit une notification et peut être révoqué | 2 à 3 semaines |
| **J13 — Application Android** | Appli Kotlin, voix en flux, notifications sans Google, confirmations biométriques, écran HyperOS, hors connexion | TEL-01, 03 à 05, 07, 08, SEC-15 | Confirmer un envoi depuis le POCO hors de chez soi, en respectant PERF-04 | 1 à 2 mois |
| **J14 — Mac** | Agent macOS, client vocal, outils macOS, secours | MAC-01 à 05, MULTI-06 | PC éteint : le Mac répond aux commandes simples et le signale | 3 à 5 semaines |
| **J15 — Contexte et continuité** | Position, continuité, outils inter-appareils | TEL-06, MULTI-03/04, INI-11 | Un rappel « quand je passe devant… » se déclenche | 3 à 4 semaines |
| **J16 — Voix maximum** | Mot de réveil personnalisé (PC + téléphone), locuteur, écho, voix expressive | VOX-10 à 13, TEL-02, PERF-11 | < 1 faux déclenchement par soirée ; batterie du téléphone < 4 %/jour | 1 à 1,5 mois |
| **J17 — Intelligence maximum** | Batterie de 200 commandes, planification, LoRA, évaluation continue, agent écran | IA-01 à 06 | > 95 % sur 200 commandes, sans régression de performance | 2 à 3 mois |
| **J18 — Initiative maximum** | Proactivité réglable, coach en direct | INI-10, INI-12 | Une semaine de suggestions jugées utiles | 1 à 2 mois |

**Durée totale J0 → J18** : environ **7 à 13 mois** avec validations régulières. Version
multi-appareils utilisable au quotidien visée en environ **2 mois**.

## 10. Risques

| Risque | Conséquence | Parade |
|---|---|---|
| HyperOS tue les applications en arrière-plan | Plus de notifications ni de mot de réveil sur le téléphone | TEL-08 (écran guidé), service de premier plan, test sur une journée complète |
| Mot de réveil permanent trop gourmand sur le téléphone | Batterie vidée | Modèle minuscule, coupure sous un seuil de batterie, PERF-11 mesuré |
| Latence 4G/5G + Tailscale trop élevée | Jarvis lent dehors | Audio Opus en flux, détection de parole sur le téléphone, PERF-04 mesuré |
| Le Mac 8 Go sature avec le modèle de secours | Mac ralenti | Chargement à la demande, déchargement après inactivité |
| Fine-tuning impossible sur AMD sous Windows | IA-03 bloquée | Vérification en début de J17 ; sinon, consignes + mémoire |
| Une optimisation dégrade la qualité des réponses | Jarvis plus rapide mais plus bête | Chaque optimisation validée par la batterie de commandes ET le banc |
| Surface d'attaque élargie | Accès non voulu | SEC-10 à 15, révocation, journal par appareil |

## 11. Ce que Mathieu fournit

- Tailscale installé sur le PC, le Mac et le POCO.
- Android Studio sur le PC de jeu (compilation de l'APK) ; le mode développeur activé sur le
  POCO pour l'installation.
- La quantité de mémoire du POCO (8 ou 12 Go).
- Des enregistrements de sa voix pour VOX-10 et VOX-11.
- Les mesures du banc de performance et les tests sur chaque appareil à la fin de chaque lot.
