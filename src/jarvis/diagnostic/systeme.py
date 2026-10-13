"""Relevé du matériel : OS, CPU, RAM, GPU, pilote, disques, mémoire vidéo utilisée."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import psutil


def powershell_json(commande: str, delai: float = 30) -> object:
    """Exécute une commande PowerShell et décode sa sortie JSON (None si indisponible)."""
    if sys.platform != "win32":
        return None
    try:
        sortie = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", commande + " | ConvertTo-Json -Depth 3"],
            capture_output=True, text=True, timeout=delai, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if sortie.returncode != 0 or not sortie.stdout.strip():
        return None
    try:
        return json.loads(sortie.stdout)
    except json.JSONDecodeError:
        return None


def _en_liste(valeur: object) -> list:
    if valeur is None:
        return []
    return valeur if isinstance(valeur, list) else [valeur]


def gpus() -> list[dict]:
    """Cartes graphiques vues par Windows (nom, pilote)."""
    brut = powershell_json(
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate,AdapterRAM"
    )
    return [
        {"nom": g.get("Name"), "pilote": g.get("DriverVersion"), "date_pilote": str(g.get("DriverDate") or "")}
        for g in _en_liste(brut)
    ]


def memoire_video_utilisee() -> dict[str, int]:
    """Mémoire vidéo dédiée utilisée par carte (octets). Classe WMI : noms non traduits."""
    brut = powershell_json(
        "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory"
        " | Select-Object Name,DedicatedUsage"
    )
    return {str(e.get("Name")): int(e.get("DedicatedUsage") or 0) for e in _en_liste(brut)}


def vram_utilisee_max() -> int:
    """Mémoire dédiée de la carte la plus chargée (la carte de jeu, sur le PC de jeu)."""
    valeurs = memoire_video_utilisee().values()
    return max(valeurs, default=0)


def nom_cpu() -> str:
    brut = powershell_json("Get-CimInstance Win32_Processor | Select-Object Name")
    liste = _en_liste(brut)
    if liste and liste[0].get("Name"):
        return liste[0]["Name"].strip()
    return platform.processor()


def disques() -> list[dict]:
    resultat = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = shutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        resultat.append({"point": p.mountpoint, "total_go": round(u.total / 1e9), "libre_go": round(u.free / 1e9)})
    return resultat


def releve(dossier_donnees: Path) -> dict:
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "python": platform.python_version(),
        "cpu": nom_cpu(),
        "coeurs_physiques": psutil.cpu_count(logical=False),
        "coeurs_logiques": psutil.cpu_count(logical=True),
        "ram_go": round(psutil.virtual_memory().total / 1e9, 1),
        "gpus": gpus(),
        "disques": disques(),
        "dossier_donnees": str(dossier_donnees),
        "vulkan_present": Path(r"C:\Windows\System32\vulkan-1.dll").exists() if sys.platform == "win32" else None,
    }
