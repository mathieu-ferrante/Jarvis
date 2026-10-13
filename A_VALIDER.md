# À lancer ou à vérifier sur le PC de jeu

Tout ce qui dépend du GPU, du micro ou de la latence ne peut être validé que sur le PC de jeu.
Chaque entrée : quoi lancer, comment, résultat attendu, et quoi me renvoyer.

---

## V0-1 — Diagnostic complet (lot J0) · **prioritaire, bloque le choix définitif des modèles**

**Durée** : 10 min de présence (dont 2 min au micro), puis 1 à 2 h automatiques.
**Place disque** : environ 45 Go sur un NVMe (modèles et outils, hors du dépôt).

### Avant de commencer

1. Pilote AMD Adrenalin à jour (il fournit Vulkan).
2. Python 3.13 installé : `winget install Python.Python.3.13` (ou python.org, cocher « Add to PATH »).
3. Le dépôt Jarvis copié sur le PC de jeu (voir la question posée sur la façon de le transférer).
4. Fermer les jeux, le navigateur et tout ce qui utilise le GPU pendant la mesure.

### Lancer

Double-cliquer sur `diagnostic.cmd` à la racine du dépôt, ou dans un terminal :

```
diagnostic.cmd --donnees D:\Jarvis
```

(`--donnees` choisit où ranger les 45 Go de modèles : un NVMe de préférence. Sans cette option :
`%LOCALAPPDATA%\Jarvis`.)

1. Le script liste ce qu'il va télécharger (github.com et huggingface.co uniquement, fichiers
   vérifiés par SHA-256) et demande confirmation : répondre `o`.
2. **Étape micro** (environ 2 min) : suivre les consignes à l'écran, parler à sa distance
   habituelle du micro. Il demandera : 4 s de silence, « Hey Jarvis » ×2, « Jarvis » seul ×2,
   une phrase sans le mot, puis 5 phrases à lire.
3. Laisser tourner. Ne pas jouer ni utiliser le GPU pendant ce temps.

Options utiles : `--sans-micro` (sauter l'étape micro), `--avec-moe` (ajoute Gemma 4 26B-A4B,
17 Go de plus), `--avec-rocm` (essaie aussi llama.cpp ROCm), `--etapes llm` (refaire seulement
les modèles de langage).

### Résultat attendu

- Dans « Matériel » : une ligne `llama.cpp voit : Vulkan0: AMD Radeon RX 6750 XT (… MiB …)`.
  Si la carte n'apparaît pas, le pilote Vulkan est en cause : me le dire.
- Modèles 9 à 14 G : génération de l'ordre de 30 à 60 jetons/s sur GPU, « Mémoire » sous 11 Go.
- Transcription : latence médiane de quelques centaines de ms sur le 5800X.
- Un rapport `diagnostic-resultats\<date>\rapport.md` et les données `diagnostic.json`.

### À me renvoyer

- `rapport.md` et `diagnostic.json` du dossier `diagnostic-resultats\<date>\`.
- **Pas** les dossiers `micro\` et `corpus\` : ils contiennent ta voix, ils restent sur ton PC.
- Ton avis sur les voix : écouter les fichiers de `diagnostic-resultats\<date>\ecoute\`
  (`piper-siwis.wav`, `piper-tom.wav`, `piper-upmc.wav`, `kokoro-ff_siwis.wav`,
  `kokoro-ff_siwis-fp32.wav`) et les classer de la préférée à la moins aimée.
- Ton avis sur le français des modèles : la section « Français : réponses à relire » du
  rapport. Lequel parle le mieux ?

---

## Valeurs provisoires à confirmer par V0-1

Voir la section « Valeurs provisoires » de [PLAN.md](PLAN.md) : elles servent à avancer sur les
lots suivants mais **rien n'est validé tant que V0-1 n'a pas tourné sur le PC de jeu**.
