"""Configuration de Jarvis : valeurs par défaut + fichier `jarvis.toml` dans le dossier des données.

Le fichier n'est jamais commité (il est hors du dépôt). Les secrets n'y figurent pas : ils sont
chiffrés à part (voir `jarvis.secrets`).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

from jarvis import chemins


@dataclass
class ConfigLLM:
    # Valeurs PROVISOIRES (PLAN.md) en attendant le diagnostic sur le PC de jeu
    principal: str = "qwen3.5-9b"
    rapide: str = "qwen3.5-9b"  # même modèle : un seul en VRAM
    mode_jeu: str = "qwen3.5-4b"  # sur CPU pendant une partie
    backend: str = "vulkan"  # vulkan, cpu ou rocm
    contexte: int = 16384
    port: int = 8731  # llama-server principal, 127.0.0.1 uniquement
    port_embeddings: int = 8732
    url_externe: str = ""  # serveur compatible OpenAI déjà lancé ailleurs EN LOCAL (tests, dev)
    temperature: float = 0.3
    max_etapes_agent: int = 10
    # Optimisations, PROVISOIRES jusqu'à la mesure sur le PC de jeu (A_VALIDER.md)
    speculatif: str = "brouillon"  # aucun, brouillon, mtp, ngram
    brouillon: str = "qwen3.5-0.8b"
    cache_kv: str = "q8_0"
    reflexion: str = "auto"  # auto (demandes complexes), toujours, jamais
    souvenirs_automatiques: bool = True  # extraire les faits durables des conversations


@dataclass
class ConfigVoix:
    tts: str = "piper-siwis"
    stt: str = "parakeet-onnx"  # parakeet-onnx ou faster-whisper
    fils_stt: int = 4
    seuil_reveil: float = 0.5
    seuil_reveil_bas: float = 0.15  # en dessous de 0,5, on vérifie « Jarvis » par la transcription
    fin_de_parole_ms: int = 400
    anticipation_ms: int = 200  # transcription anticipée dès 200 ms de silence (J11)
    duree_max_phrase_s: float = 15.0
    ecoute_continue_s: float = 6.0  # VOX-05
    interruption: str = "reveil"  # "reveil" (dire « Jarvis ») ou "vad" (toute parole, casque requis)
    raccourci_parler: str = "ctrl+alt+j"
    raccourci_arret: str = "ctrl+alt+k"  # SEC-07
    micro: str = ""  # nom (ou index) du périphérique d'entrée ; vide = défaut
    sortie: str = ""


@dataclass
class ConfigServeur:
    port: int = 8730
    hotes: list[str] = field(default_factory=lambda: ["127.0.0.1"])  # + IP Tailscale ajoutée au démarrage
    tailscale: bool = True


@dataclass
class ConfigMemoire:
    dossier_sauvegarde: str = ""  # ex. E:\Sauvegardes\Jarvis (disque dur de 4 To)
    sauvegarde_heures: int = 24
    documents_indexes: list[str] = field(default_factory=list)


@dataclass
class ConfigInitiative:
    briefing: bool = True
    ville_meteo: str = "Marseille"
    latitude: float = 43.2965
    longitude: float = 5.3698
    suggestions: bool = True


@dataclass
class ConfigJeu:
    detection: bool = True
    # Exécutables considérés comme des jeux (en plus de la détection plein écran + GPU)
    executables: list[str] = field(default_factory=lambda: [
        "cs2.exe", "League of Legends.exe", "LeagueClientUx.exe", "GeometryDash.exe",
        "TFT.exe", "VALORANT-Win64-Shipping.exe",
    ])
    alertes_autorisees: list[str] = field(default_factory=lambda: ["rappel"])  # VOX-07


@dataclass
class ConfigIntegrations:
    postgame_url: str = "http://127.0.0.1:8765"  # port par défaut de Postgame
    home_assistant_url: str = ""  # ex. http://homeassistant.local:8123
    # Mail (mot de passe d'application dans le coffre : imap_mot_de_passe)
    imap_hote: str = ""  # ex. imap.gmail.com
    imap_utilisateur: str = ""
    smtp_hote: str = ""  # ex. smtp.gmail.com (port 465 SSL ou 587 STARTTLS)
    smtp_port: int = 465
    expediteurs_importants: list[str] = field(default_factory=list)  # pour le briefing
    # Agenda : CalDAV (lecture + création ; mot de passe : caldav_mot_de_passe) ou adresse iCal privée (lecture)
    caldav_url: str = ""
    caldav_utilisateur: str = ""
    ics_url: str = ""  # ex. adresse secrète au format iCal de Google Agenda
    # Discord (jeton du bot dans le coffre : discord_jeton_bot)
    discord_salons: dict = field(default_factory=dict)  # {"general": "123…"} salons lisibles
    discord_contacts: dict = field(default_factory=dict)  # {"théo": "456…"} identifiants pour les MP
    depots: list[str] = field(default_factory=list)  # projets perso (OUT-DEV)
    home_assistant_entites: list[str] = field(default_factory=list)  # restreindre (vide = toutes)


@dataclass
class Config:
    llm: ConfigLLM = field(default_factory=ConfigLLM)
    voix: ConfigVoix = field(default_factory=ConfigVoix)
    serveur: ConfigServeur = field(default_factory=ConfigServeur)
    memoire: ConfigMemoire = field(default_factory=ConfigMemoire)
    initiative: ConfigInitiative = field(default_factory=ConfigInitiative)
    jeu: ConfigJeu = field(default_factory=ConfigJeu)
    integrations: ConfigIntegrations = field(default_factory=ConfigIntegrations)
    routines: dict = field(default_factory=dict)


def _appliquer(objet, valeurs: dict) -> None:
    for f in fields(objet):
        if f.name not in valeurs:
            continue
        actuel = getattr(objet, f.name)
        if is_dataclass(actuel) and isinstance(valeurs[f.name], dict):
            _appliquer(actuel, valeurs[f.name])
        else:
            setattr(objet, f.name, valeurs[f.name])


def chemin_config() -> Path:
    return chemins.dossier_donnees() / "jarvis.toml"


def charger(chemin: Path | None = None) -> Config:
    config = Config()
    chemin = chemin or chemin_config()
    if chemin.exists():
        _appliquer(config, tomllib.loads(chemin.read_text("utf-8")))
    return config


MODELE_FICHIER = """# Configuration de Jarvis. Toutes les clés sont facultatives ; voir src/jarvis/config.py.
# Les secrets (mots de passe, jetons) ne vont PAS ici : `python -m jarvis secrets`.

[llm]
# Valeurs provisoires : à remplacer par les choix du diagnostic J0 (rapport.md).
principal = "qwen3.5-9b"
rapide = "qwen3.5-9b"
mode_jeu = "qwen3.5-4b"
backend = "vulkan"

[voix]
tts = "piper-siwis"
stt = "parakeet-onnx"
interruption = "reveil"   # "vad" si tu portes un casque

[memoire]
dossier_sauvegarde = ""   # ex. 'E:\\\\Sauvegardes\\\\Jarvis'

[initiative]
ville_meteo = "Marseille"
latitude = 43.2965
longitude = 5.3698

[integrations]
postgame_url = "http://127.0.0.1:8765"
home_assistant_url = ""

# Routines (OUT-ROU) : une liste d'étapes {outil, arguments}.
[routines.mode_jeu]
description = "Ferme le superflu, lance Discord et Steam, met la playlist"
etapes = [
  { outil = "fermer_application", args = { nom = "chrome" } },
  { outil = "lancer_application", args = { nom = "discord" } },
  { outil = "lancer_application", args = { nom = "steam" } },
  { outil = "jouer_musique", args = { recherche = "playlist jeu" } },
]
"""


def creer_si_absent() -> Path:
    chemin = chemin_config()
    if not chemin.exists():
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(MODELE_FICHIER, "utf-8")
    return chemin
