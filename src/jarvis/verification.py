"""`python -m jarvis verifier` : contrôle de l'installation en une commande, sur le PC de jeu.

Chaque contrôle renvoie un statut (ok, attention, échec), un libellé et un détail. Le bilan est
affiché et écrit dans `rapport_verification.md` (dossier des données), à renvoyer à Claude.
Rien ne sort du PC : aucun accès réseau, sauf la tentative volontairement refusée par la garde.
Le rapport ne contient aucun secret (seulement la présence ou non des entrées du coffre).
"""

from __future__ import annotations

import importlib.util
import logging
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

OK, ATTENTION, ECHEC = "ok", "attention", "échec"
SYMBOLES = {OK: "✅", ATTENTION: "⚠️", ECHEC: "❌"}

DEPENDANCES = {
    "socle": ["numpy", "psutil", "httpx", "cryptography"],
    "voix": ["onnx_asr", "onnxruntime", "piper", "openwakeword", "sounddevice", "soundfile", "scipy", "sherpa_onnx"],
    "app": ["fastapi", "uvicorn", "websockets", "pystray", "PIL", "mss", "pynput", "bs4", "pypdf", "icalendar"],
}


@dataclass
class Controle:
    statut: str
    libelle: str
    detail: str = ""


def python() -> Controle:
    v = sys.version_info
    statut = OK if v >= (3, 13) else ECHEC
    return Controle(statut, "Python", f"{platform.python_version()} ({sys.executable})")


def dependances(trouver=importlib.util.find_spec) -> list[Controle]:
    resultats = []
    for groupe, modules in DEPENDANCES.items():
        manquants = [m for m in modules if trouver(m) is None]
        if not manquants:
            resultats.append(Controle(OK, f"Dépendances « {groupe} »", f"{len(modules)} modules"))
        else:
            # Sans la voix ou l'interface, Jarvis tourne en mode dégradé : pas bloquant pour le socle
            statut = ECHEC if groupe == "socle" else ATTENTION
            resultats.append(Controle(statut, f"Dépendances « {groupe} »",
                                      "manquent : " + ", ".join(manquants) + " → relancer installer.cmd"))
    return resultats


def configuration():
    from jarvis import config

    try:
        c = config.charger()
    except Exception as e:  # noqa: BLE001 — on rapporte
        return None, Controle(ECHEC, "Configuration", f"jarvis.toml illisible : {e}")
    return c, Controle(OK, "Configuration",
                       f"modèle {c.llm.principal}, jeu {c.llm.mode_jeu}, backend {c.llm.backend}, voix {c.voix.tts}")


def fichiers_modeles(c) -> Controle:
    from jarvis import modeles

    absents, tailles = [], []
    for f in modeles.fichiers_necessaires(c):
        p = modeles.chemin(f)
        if not p.exists():
            absents.append(f.nom)
        elif f.taille and p.stat().st_size != f.taille:
            tailles.append(f.nom)
    if absents or tailles:
        detail = "; ".join(filter(None, [
            ("absents : " + ", ".join(absents)) if absents else "",
            ("taille inattendue : " + ", ".join(tailles)) if tailles else ""]))
        return Controle(ECHEC, "Modèles et outils", detail + " → python -m jarvis installer")
    return Controle(OK, "Modèles et outils", f"{len(modeles.fichiers_necessaires(c))} fichiers présents")


def gpu_vulkan(c, executer=subprocess.run) -> Controle:
    """Le llama-server du backend choisi voit-il la carte ? (`--list-devices`, sans charger de modèle)."""
    from jarvis.llm.serveur import dossier_binaires

    try:
        dossier = dossier_binaires(c.llm.backend)
    except Exception as e:  # noqa: BLE001
        return Controle(ECHEC, f"llama-server ({c.llm.backend})", str(e))
    try:
        r = executer([str(dossier / "llama-server.exe"), "--list-devices"], capture_output=True, text=True,
                     timeout=60, encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return Controle(ECHEC, f"llama-server ({c.llm.backend})", f"ne se lance pas : {e}")
    sortie = (r.stdout or "") + (r.stderr or "")
    lignes = [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]
    appareils = [ligne for ligne in lignes if re.match(r"(Vulkan|ROCm)\d+:", ligne)]
    if c.llm.backend == "cpu":
        return Controle(ATTENTION, "llama-server (cpu)", "backend CPU : la carte graphique n'est pas utilisée")
    if not appareils:
        return Controle(ECHEC, f"llama-server ({c.llm.backend})",
                        "aucune carte vue (pilote AMD à jour ?) : " + " | ".join(lignes[-3:]))
    amd = any(m in " ".join(appareils).lower() for m in ("radeon", "amd", "6750"))
    return Controle(OK if amd else ATTENTION, f"llama-server ({c.llm.backend})", " | ".join(appareils))


def contexte_modele(c) -> Controle:
    """Le préfixe fixe (consignes + schémas de tous les outils) doit laisser de la place à la conversation."""
    from jarvis.agent import budget
    from jarvis.agent.contexte import CONSIGNES
    from jarvis.outils.registre import Registre

    schemas = Registre().charger_tout().schemas()
    fixe = budget.tokens_outils(schemas) + budget.tokens(CONSIGNES)
    detail = f"{c.llm.contexte} tokens par emplacement, préfixe ≈ {fixe} ({len(schemas)} outils)"
    if fixe + budget.MARGE_MINIMALE > c.llm.contexte:
        return Controle(ATTENTION, "Contexte du modèle", detail + " → outils essentiels seulement : passer "
                        "llm.contexte à 16384 ou plus dans jarvis.toml")
    return Controle(OK, "Contexte du modèle", detail)


def micro(c) -> Controle:
    try:
        import sounddevice as sd
    except ImportError:
        return Controle(ATTENTION, "Micro", "sounddevice absent : voix indisponible")
    try:
        if c.voix.micro:
            p = sd.query_devices(int(c.voix.micro) if c.voix.micro.isdigit() else c.voix.micro, "input")
        else:
            p = sd.query_devices(kind="input")
    except Exception as e:  # noqa: BLE001
        return Controle(ECHEC, "Micro", f"introuvable : {e}")
    return Controle(OK, "Micro", f"{p['name']} ({int(p['default_samplerate'])} Hz)")


def coffre() -> Controle:
    from jarvis.securite import secrets

    try:
        ok = secrets.dechiffrer(secrets.chiffrer(b"jarvis")) == b"jarvis"
    except Exception as e:  # noqa: BLE001
        return Controle(ECHEC, "Coffre (DPAPI)", str(e))
    if not ok:
        return Controle(ECHEC, "Coffre (DPAPI)", "le déchiffrement ne redonne pas la valeur")
    noms = sorted(secrets.Coffre().noms())  # les noms seulement, jamais les valeurs
    return Controle(OK, "Coffre (DPAPI)", f"{len(noms)} entrées" + (f" : {', '.join(noms)}" if noms else ""))


def garde_reseau() -> Controle:
    """SEC-04 : une sortie vers un fournisseur d'IA doit être refusée avant toute résolution DNS."""
    from jarvis.securite.reseau import GardeReseau, SortieRefusee

    logging.getLogger("jarvis.securite.reseau").setLevel(logging.ERROR)  # le refus attendu n'est pas une alerte
    garde = GardeReseau()
    garde.installer()  # crochet d'audit définitif pour ce processus : la commande se termine juste après
    try:
        socket.getaddrinfo("api.openai.com", 443)
    except SortieRefusee:
        return Controle(OK, "Garde réseau (SEC-04)", "sortie vers api.openai.com refusée")
    except OSError as e:
        return Controle(ECHEC, "Garde réseau (SEC-04)", f"non refusée par la garde (erreur réseau : {e})")
    return Controle(ECHEC, "Garde réseau (SEC-04)", "la résolution a abouti : la garde ne bloque pas")


def ports(c) -> list[Controle]:
    resultats = []
    for nom, port in (("interface", c.serveur.port), ("modèle", c.llm.port), ("plongements", c.llm.port_embeddings)):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            resultats.append(Controle(OK, f"Port {port} ({nom})", "libre"))
        except OSError:
            resultats.append(Controle(ATTENTION, f"Port {port} ({nom})", "occupé (Jarvis déjà lancé ?)"))
        finally:
            s.close()
    return resultats


def tailscale() -> Controle:
    chemin = shutil.which("tailscale") or next(
        (str(p) for p in (Path(r"C:\Program Files\Tailscale\tailscale.exe"),) if p.exists()), None)
    if not chemin:
        return Controle(ATTENTION, "Tailscale", "absent : téléphone et Mac injoignables hors du PC")
    return Controle(OK, "Tailscale", chemin)


def reveil_perso() -> Controle:
    from jarvis import chemins

    p = chemins.dossier_modeles() / "reveil" / "jarvis_perso.onnx"
    if p.exists():
        return Controle(OK, "Mot de réveil personnalisé", f"entraîné le {datetime.fromtimestamp(p.stat().st_mtime):%d/%m/%Y}")
    return Controle(ATTENTION, "Mot de réveil personnalisé",
                    "absent (modèle générique utilisé) → enroler-voix puis entrainer-reveil")


def disque() -> Controle:
    from jarvis import chemins

    dossier = chemins.dossier_donnees()
    libre = shutil.disk_usage(dossier if dossier.exists() else dossier.anchor).free / 1e9
    return Controle(OK if libre >= 20 else ATTENTION, "Espace disque", f"{libre:.0f} Go libres ({dossier})")


def tout_verifier(gpu: bool = True) -> list[Controle]:
    resultats = [python(), *dependances()]
    c, ctrl = configuration()
    resultats.append(ctrl)
    if c is not None:
        resultats.append(fichiers_modeles(c))
        resultats.append(contexte_modele(c))
        if gpu:
            resultats.append(gpu_vulkan(c))
        resultats.append(micro(c))
        resultats += ports(c)
    resultats += [coffre(), tailscale(), reveil_perso(), disque(), garde_reseau()]
    return resultats


def rapport(resultats: list[Controle]) -> str:
    echecs = sum(r.statut == ECHEC for r in resultats)
    attentions = sum(r.statut == ATTENTION for r in resultats)
    lignes = [f"# Vérification de Jarvis — {datetime.now():%d/%m/%Y %H:%M}", "",
              f"{platform.system()} {platform.release()} · {platform.machine()} · "
              f"{echecs} échec(s), {attentions} point(s) d'attention", "",
              "| | Contrôle | Détail |", "|---|---|---|"]
    lignes += [f"| {SYMBOLES[r.statut]} | {r.libelle} | {r.detail.replace('|', '/')} |" for r in resultats]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    from jarvis import chemins

    argv = argv or []
    resultats = tout_verifier(gpu="--sans-gpu" not in argv)
    texte = rapport(resultats)
    for r in resultats:
        print(f"{SYMBOLES[r.statut]} {r.libelle} : {r.detail}")
    dossier = chemins.dossier_donnees()
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "rapport_verification.md").write_text(texte, "utf-8")
    print(f"\nRapport : {dossier / 'rapport_verification.md'} (à renvoyer à Claude, il ne contient aucun secret)")
    return 1 if any(r.statut == ECHEC for r in resultats) else 0
