"""Emplacements des données de Jarvis (modèles, outils, résultats), hors du dépôt.

Ordre de priorité : variable JARVIS_DONNEES, puis le pointeur `emplacement.txt` (écrit quand on
choisit un autre disque avec `--donnees`), puis %LOCALAPPDATA%\\Jarvis.
"""

import os
from pathlib import Path


def dossier_par_defaut() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Jarvis"


def dossier_donnees() -> Path:
    if env := os.environ.get("JARVIS_DONNEES"):
        return Path(env)
    pointeur = dossier_par_defaut() / "emplacement.txt"
    if pointeur.exists():
        cible = pointeur.read_text("utf-8").strip()
        if cible:
            return Path(cible)
    return dossier_par_defaut()


def memoriser_emplacement(dossier: Path) -> None:
    """Retient un autre emplacement (ex. D:\\Jarvis sur le NVMe) pour les prochains lancements."""
    defaut = dossier_par_defaut()
    defaut.mkdir(parents=True, exist_ok=True)
    pointeur = defaut / "emplacement.txt"
    if Path(dossier).resolve() == defaut.resolve():
        pointeur.unlink(missing_ok=True)
    else:
        pointeur.write_text(str(Path(dossier).resolve()), "utf-8")


def dossier_modeles() -> Path:
    return dossier_donnees() / "modeles"


def dossier_outils() -> Path:
    return dossier_donnees() / "outils"
