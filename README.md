# Jarvis

Assistant personnel vocal, le plus puissant possible, **100 % local** : aucune information ne
sort du PC à cause de Jarvis, aucun appel à une IA dans le cloud.

- Cahier des charges : [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md) (complété par [BRIEF.md](BRIEF.md))
- Avancement et décisions : [PLAN.md](PLAN.md)
- À lancer sur le PC de jeu : [A_VALIDER.md](A_VALIDER.md)

## État

| Lot | État |
|---|---|
| J0 — Diagnostic et choix par la mesure | Script prêt, testé en mode rapide sur le poste de développement. **Pas encore lancé sur le PC de jeu** |
| J1 à J10 | À faire |

## Diagnostic (lot J0)

Sur le PC de jeu, double-cliquer sur `diagnostic.cmd` (mode opératoire complet dans
[A_VALIDER.md](A_VALIDER.md)). Il prépare un environnement Python 3.13, télécharge les outils
et modèles candidats (vérifiés par SHA-256, depuis github.com et huggingface.co uniquement),
puis mesure :

- le matériel et ce que voit llama.cpp (Vulkan) ;
- les modèles de langage : débit, latence jusqu'à la première phrase, batterie de 29 commandes
  d'appel d'outils en français, qualité du français, vision ;
- la transcription (faster-whisper, whisper.cpp, Parakeet), sur voix de synthèse, bruitée et au micro ;
- les voix de synthèse (Piper, Kokoro), avec des fichiers à écouter ;
- le mot de réveil (coût CPU, détections).

Il écrit `diagnostic-resultats/<date>/rapport.md` avec les décisions prises par la mesure.

## Développement

Poste de développement (sans GPU de jeu) :

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[voix,dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m jarvis.diagnostic --rapide --sans-micro
```

Le mode `--rapide` utilise de petits modèles (Qwen3.5 0.8B, Whisper base, Parakeet q4) pour
valider le script sans le matériel cible. Les modèles et outils sont rangés hors du dépôt, dans
`%LOCALAPPDATA%\Jarvis` (ou le dossier donné par `JARVIS_DONNEES` / `--donnees`).

## Structure

```
src/jarvis/
  telechargement.py      téléchargement vérifié (liste blanche, SHA-256)
  chemins.py             emplacement des données hors du dépôt
  diagnostic/            lot J0 : catalogue, mesures, décisions, rapport
    donnees/             batterie d'appel d'outils, phrases de test
tests/                   tests automatisés (pytest)
diagnostic.cmd / .ps1    lanceur Windows du diagnostic
```
