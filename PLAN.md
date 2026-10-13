# Jarvis — plan et suivi

Référence : [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md). Ce que Mathieu doit lancer sur le PC
de jeu : [A_VALIDER.md](A_VALIDER.md).

Légende : `[x]` fait et testé sur le poste de développement · `[~]` fait, **en attente de
validation sur le PC de jeu** · `[ ]` à faire.

## Avancement des lots

| Lot | État | Commentaire |
|---|---|---|
| J0 — Diagnostic et choix par la mesure | `[~]` | Script prêt et validé en mode rapide ici ; les chiffres réels viendront du PC de jeu |
| J1 — Boucle vocale | `[ ]` | |
| J2 — Cœur et sécurité | `[ ]` | |
| J3 — Outils PC | `[ ]` | |
| J4 — Mémoire | `[ ]` | |
| J5 — Interface et téléphone | `[ ]` | |
| J6 — Web et vision | `[ ]` | |
| J7 — Communication | `[ ]` | |
| J8 — Initiative | `[ ]` | |
| J9 — Coach de jeux et projets | `[ ]` | |
| J10 — Maison connectée | `[ ]` | |

## J0 — Diagnostic et choix par la mesure

- [x] Recherche : état des outils au 2026-10-13 (llama.cpp, whisper.cpp, modèles, voix, réveil)
- [x] Paquet Python `jarvis` (src/), environnement 3.13, tests, linter
- [x] Téléchargement vérifié (liste blanche d'hôtes, SHA-256 figés, reprise)
- [x] Relevé matériel (CPU, RAM, GPU, pilote, disques, mémoire vidéo via WMI)
- [x] Modèles de langage : débit (llama-bench), latence perçue en diffusion, batterie d'appel
      d'outils en français (29 cas), échantillons de français, test de vision
- [x] Transcription : faster-whisper CPU, whisper.cpp CPU, Parakeet v3 ; WER propre / bruité / micro
- [x] Voix : Piper (3 voix FR) et Kokoro (ff_siwis) ; latence de la première phrase, fichiers à écouter
- [x] Mot de réveil : coût CPU et détections (openWakeWord « hey jarvis »)
- [x] Étape micro interactive (bruit ambiant, mot de réveil, phrases lues)
- [x] Règles de décision et rapport (Markdown + JSON)
- [x] Lanceur Windows `diagnostic.cmd` / `diagnostic.ps1`
- [x] Exécution complète en mode `--rapide` sur le poste de développement (13 min, aucune erreur)
- [ ] **Exécution complète sur le PC de jeu** (A_VALIDER.md, V0-1)
- [ ] Trancher définitivement avec les chiffres du PC de jeu, mettre à jour les décisions ci-dessous

## Décisions

| # | Date | Décision | Pourquoi |
|---|---|---|---|
| D1 | 2026-10-13 | Serveur de modèles : **llama.cpp `llama-server` directement**, binaire officiel Windows **Vulkan**, version figée `b11583` | Seule voie officielle pour la RX 6750 XT sous Windows ; API compatible OpenAI ; pas de couche Ollama / LM Studio (télémétrie, version de llama.cpp imposée). Lancé avec `--offline --no-webui --host 127.0.0.1` |
| D2 | 2026-10-13 | Candidats principaux : **Qwen3.5 9B, Gemma 4 12B, Ministral 3 14B** (Q4_K_M) ; routage : **Qwen3.5 4B, Gemma 4 E4B** ; en option : Gemma 4 26B-A4B (MoE, experts en RAM) | Les plus récents de 8 à 14 G paramètres, tous multimodaux (vision BRN-06 avec le même modèle), tous publiés en GGUF |
| D3 | 2026-10-13 | ROCm : mesuré en option seulement (`--avec-rocm`) | gfx1031 n'est pas officiellement pris en charge par ROCm sous Windows ; on ne le suppose pas, on le mesure |
| D4 | 2026-10-13 | Transcription, candidats : faster-whisper CPU int8 (small, medium, large-v3-turbo), whisper.cpp CPU (small, large-v3-turbo q8), **Parakeet TDT 0.6B v3** (via whisper.cpp) | faster-whisper n'a pas de GPU AMD ; whisper.cpp ne publie pas de binaire Windows Vulkan (option `--whisper-vulkan` si compilé à la main) ; Parakeet v3 gère le français et est réputé très rapide sur CPU. La transcription sur CPU laisse aussi le GPU au jeu |
| D5 | 2026-10-13 | Voix, candidats : Piper (siwis, tom, upmc) et Kokoro (ff_siwis, int8 et fp32) | Les deux tournent sur CPU en local ; Kokoro réputé plus naturel, Piper plus rapide. Le choix final se fait à l'oreille de Mathieu |
| D6 | 2026-10-13 | Mot de réveil : **openWakeWord**, modèle pré-entraîné « hey jarvis » en provisoire ; modèle « Jarvis » seul à entraîner en J1 | Porcupine écarté : sa clé d'accès est vérifiée en ligne (contraire à SEC-04). Aucun modèle « Jarvis » seul pré-entraîné n'existe |
| D7 | 2026-10-13 | Télémétrie coupée à l'import de `jarvis` (Hugging Face, etc.) ; téléchargements uniquement depuis github.com / huggingface.co, empreintes vérifiées | Règle absolue SEC-04 |
| D8 | 2026-10-13 | Seuils de décision : NF-02 ≥ 90 % (écarté sous 80 %), budget NF-01 réparti en fin de parole 400 ms + transcription ≤ 500 ms + première phrase du modèle ≤ 700 ms + première phrase de voix ≤ 300 ms | Découpage provisoire de 1 500 ms, révisable en J1 (voir `decision.py`) |

## Valeurs provisoires (en attendant le PC de jeu)

Utilisées pour avancer sur les lots suivants. **Rien de tout ceci n'est validé sur le PC de jeu.**

| Brique | Valeur provisoire | Source |
|---|---|---|
| Modèle principal | **Qwen3.5 9B** Q4_K_M, vision par son mmproj | Le plus petit des trois candidats (5,7 Go + 0,9 Go) : marge pour le contexte et un seul modèle en VRAM ; réputé le meilleur en appel d'outils. Non mesuré sur la RX 6750 XT |
| Modèle rapide / routage | le même (un seul modèle chargé) | Évite deux modèles en 12 Go ; à revoir selon la latence mesurée |
| Mode jeu (CPU) | **Qwen3.5 4B** sur CPU seul | Plus petit candidat de routage ; débit CPU du 5800X non mesuré |
| Transcription | **Parakeet TDT 0.6B v3** (whisper.cpp, CPU) | Mesuré sur le poste de dev (i5-1335U) : WER 14 % contre 32 % pour Whisper base, 250 ms contre 710 ms. Whisper small / turbo non mesurés ici (trop lourds pour le réseau du poste) |
| Voix | **Piper fr_FR-siwis-medium** | Mesuré sur le poste de dev : 170 ms pour la première phrase ; Kokoro 1,6 s (trop lent ici, à revoir sur le 5800X et à l'oreille) |
| Mot de réveil | openWakeWord « hey jarvis », seuil 0,5 | D6. Constat local : 0/8 détections avec les voix de synthèse françaises (prononciation), 4/4 avec des voix anglaises ; le bruit seul monte à 0,49. Un modèle « Jarvis » entraîné sur des prononciations françaises est nécessaire (J1) |
