# Jarvis — consignes pour Claude

Le projet est entièrement décrit dans [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md), complété
par [BRIEF.md](BRIEF.md). C'est la référence : les lire en entier avant toute chose.

## Mode de travail : autonomie de A à Z

Mathieu veut que Claude mène **tout le projet, du lot J0 au lot J10, sans s'arrêter**.

- **Enchaîner les lots** dans l'ordre du cahier des charges, sans demander de validation entre
  deux lots ni entre deux étapes. Pour chaque lot : planifier → se documenter (doc officielle,
  vérifier les outils et leur support AMD / Vulkan plutôt que supposer) → coder → tester →
  corriger jusqu'au vert → commiter → mettre à jour `PLAN.md` et le README → passer au lot
  suivant.
- **Trancher seul** les choix techniques ordinaires en suivant le cahier des charges ; les
  choix marqués « à départager » se tranchent **par la mesure** (J0). Noter les décisions
  dans `PLAN.md`.
- **Ne s'arrêter que pour poser une question**, dans l'un de ces cas :
  1. une décision qui appartient à Mathieu et que ni le cahier des charges ni le code ne
     permettent de trancher ;
  2. une action que seul Mathieu peut faire : lancer le diagnostic ou un test sur le PC de
     jeu, brancher un compte (mail, agenda, Discord, Spotify), fournir sa liste de commandes ;
  3. une action irréversible ou visible de l'extérieur : créer un dépôt GitHub, pousser,
     publier quoi que ce soit.
- **Regrouper les questions** : en poser plusieurs d'un coup plutôt qu'une par une.
- **Ne jamais rester bloqué** : si un lot attend une mesure ou une validation sur le PC de jeu,
  l'inscrire dans `A_VALIDER.md` (quoi lancer, comment, résultat attendu), continuer avec des
  valeurs par défaut raisonnables clairement marquées comme provisoires, et avancer sur ce
  qui n'en dépend pas.
- **Dire la vérité** sur l'état réel : ce qui n'a pas tourné sur le PC de jeu n'est pas
  validé, et c'est écrit comme tel.

## Règle absolue

**Aucune information ne sort du PC à cause de Jarvis** : aucun appel à une API d'IA distante,
nulle part, jamais (voir SEC-04). Une dépendance qui contacte un service distant par défaut
(télémétrie, téléchargement implicite) doit être configurée pour ne pas le faire.

## Fichiers de suivi

- `PLAN.md` : lots, état d'avancement (cases à cocher), décisions prises. Créé au lot J0.
- `A_VALIDER.md` : ce que Mathieu doit lancer ou tester sur le PC de jeu, avec le mode
  opératoire et le résultat attendu.

## Environnement

- **Le poste de développement n'est pas le PC de jeu.** Poste Windows d'entreprise, sans GPU
  de jeu : sockets AF_UNIX bloqués, donc **Gradle ne démarre pas** (pas d'Android natif ; le
  téléphone passe par une PWA). Python 3.13 et Node 24 sont disponibles ; `uv` ne l'est pas
  (utiliser `py -3.13 -m venv`).
- Le PC de jeu, où Jarvis tourne : Ryzen 5800X, **RX 6750 XT 12 Go (AMD, pas de CUDA)**, 32 Go,
  Windows. Tout ce qui dépend du GPU, du micro ou de la latence se valide là-bas.
- Le code doit donc tourner aussi sur le poste de développement en mode dégradé (CPU, petits
  modèles, micro simulé par des fichiers audio) pour que les tests passent ici.

## Conventions

- Tout en français : code commenté, interface, voix, documentation, messages de commit.
- Un commit par étape cohérente, message à l'indicatif présent (« Ajoute… », « Corrige… »).
- Jamais de secret commité : jetons et identifiants chiffrés, hors du dépôt.
