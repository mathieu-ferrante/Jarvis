"""Emplacements des données de Jarvis (modèles, outils, résultats), hors du dépôt."""

import os
from pathlib import Path


def dossier_donnees() -> Path:
    """Dossier racine des données. Surcharge possible avec la variable JARVIS_DONNEES."""
    if env := os.environ.get("JARVIS_DONNEES"):
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Jarvis"


def dossier_modeles() -> Path:
    return dossier_donnees() / "modeles"


def dossier_outils() -> Path:
    return dossier_donnees() / "outils"
