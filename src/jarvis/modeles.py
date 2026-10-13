"""Modèles et outils utilisés par Jarvis en fonctionnement (et non plus seulement par le diagnostic).

Les choix par défaut sont les valeurs PROVISOIRES de PLAN.md, en attendant le diagnostic sur le
PC de jeu ; ils se changent dans la configuration (`jarvis.toml`) sans toucher au code.
"""

from __future__ import annotations

from pathlib import Path

from jarvis import chemins
from jarvis.diagnostic import catalogue as cat
from jarvis.telechargement import Fichier, telecharger

_PARAKEET_ONNX = ("istupakov/parakeet-tdt-0.6b-v3-onnx", "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce")


def _hf(repo_rev: tuple[str, str], chemin: str, taille: int, sha256: str, dest: str) -> Fichier:
    repo, rev = repo_rev
    return Fichier(f"https://huggingface.co/{repo}/resolve/{rev}/{chemin}", dest, taille, sha256)


# Transcription dans le processus (onnx-asr), sans rechargement à chaque phrase.
PARAKEET_ONNX = [
    _hf(_PARAKEET_ONNX, "config.json", 97,
        "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466", "parakeet-onnx/config.json"),
    _hf(_PARAKEET_ONNX, "vocab.txt", 93939,
        "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d", "parakeet-onnx/vocab.txt"),
    _hf(_PARAKEET_ONNX, "nemo128.onnx", 139764,
        "a9fde1486ebfcc08f328d75ad4610c67835fea58c73ba57e3209a6f6cf019e9f", "parakeet-onnx/nemo128.onnx"),
    _hf(_PARAKEET_ONNX, "decoder_joint-model.int8.onnx", 18202004,
        "eea7483ee3d1a30375daedc8ed83e3960c91b098812127a0d99d1c8977667a70",
        "parakeet-onnx/decoder_joint-model.int8.onnx"),
    _hf(_PARAKEET_ONNX, "encoder-model.int8.onnx", 652183999,
        "6139d2fa7e1b086097b277c7149725edbab89cc7c7ae64b23c741be4055aff09",
        "parakeet-onnx/encoder-model.int8.onnx"),
]

# Embeddings multilingues pour la mémoire sémantique (MEM-02), servis par llama-server --embedding.
EMBEDDINGS = _hf(("Qwen/Qwen3-Embedding-0.6B-GGUF", "370f27d7550e0def9b39c1f16d3fbaa13aa67728"),
                 "Qwen3-Embedding-0.6B-Q8_0.gguf", 639150592,
                 "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439",
                 "Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf")


def modele_llm(cle: str) -> cat.ModeleLLM:
    for m in cat.MODELES_LLM:
        if m.cle == cle:
            return m
    raise KeyError(f"Modèle inconnu : {cle} (connus : {', '.join(m.cle for m in cat.MODELES_LLM)})")


def voix(cle: str) -> cat.VoixTTS:
    for v in cat.VOIX_TTS:
        if v.cle == cle:
            return v
    raise KeyError(f"Voix inconnue : {cle}")


def fichiers_necessaires(config) -> list[Fichier]:
    """Tout ce qu'il faut pour faire tourner Jarvis avec la configuration donnée."""
    fichiers: list[Fichier] = [cat.LLAMA_CPP["vulkan"], cat.LLAMA_CPP["cpu"]]
    for cle in {config.llm.principal, config.llm.rapide, config.llm.mode_jeu}:
        m = modele_llm(cle)
        fichiers.append(m.gguf)
        if m.mmproj and cle == config.llm.principal:
            fichiers.append(m.mmproj)
    if config.llm.speculatif == "brouillon" and config.llm.brouillon:
        fichiers.append(modele_llm(config.llm.brouillon).gguf)
    fichiers += PARAKEET_ONNX
    fichiers.append(EMBEDDINGS)
    fichiers.append(LOCUTEUR)
    fichiers += list(voix(config.voix.tts).fichiers)
    fichiers += list(cat.OPENWAKEWORD.values())
    uniques: dict[str, Fichier] = {}
    for f in fichiers:
        uniques.setdefault(f.destination, f)
    return list(uniques.values())


def dossier_pour(f: Fichier) -> Path:
    racine = f.destination.split("/")[0]
    return chemins.dossier_outils() if racine in ("llama.cpp", "whisper.cpp") else chemins.dossier_modeles()


def chemin(f: Fichier) -> Path:
    return dossier_pour(f) / f.destination


def installer(config, verifier: bool = False) -> list[str]:
    """Télécharge ce qui manque. Renvoie les erreurs éventuelles."""
    erreurs = []
    for f in fichiers_necessaires(config):
        try:
            telecharger(f, dossier_pour(f), verifier_existant=verifier)
        except Exception as e:  # noqa: BLE001 — on continue et on rapporte
            erreurs.append(f"{f.nom} : {e}")
    return erreurs

# Empreinte vocale (VOX-11) : WeSpeaker ResNet34 (VoxCeleb, multilingue), via sherpa-onnx.
LOCUTEUR = Fichier("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
                   "wespeaker_en_voxceleb_resnet34_LM.onnx", "locuteur/wespeaker_en_voxceleb_resnet34_LM.onnx",
                   26530550, "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012")
