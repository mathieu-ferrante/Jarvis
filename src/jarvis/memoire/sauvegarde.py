"""Sauvegarde automatique et chiffrée de la mémoire (MEM-05), vers le disque de sauvegarde.

Chiffrement AES-256-GCM. La clé est aléatoire, gardée dans le coffre (DPAPI). Comme DPAPI est
lié à ce PC, Mathieu doit noter la clé de secours (`python -m jarvis sauvegarde --cle`) pour
pouvoir restaurer après une panne.
"""

from __future__ import annotations

import base64
import io
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from jarvis import chemins

ENTETE = b"JARVIS-SAUV1"
NOM_CLE = "cle_sauvegarde"
FICHIERS = ("memoire.sqlite", "journal.sqlite", "rappels.sqlite", "jarvis.toml")


def cle(coffre) -> bytes:
    valeur = coffre.lire(NOM_CLE)
    if not valeur:
        valeur = base64.urlsafe_b64encode(AESGCM.generate_key(256)).decode()
        coffre.ecrire(NOM_CLE, valeur)
    return base64.urlsafe_b64decode(valeur)


def chiffrer(donnees: bytes, cle_: bytes) -> bytes:
    nonce = os.urandom(12)
    return ENTETE + nonce + AESGCM(cle_).encrypt(nonce, donnees, ENTETE)


def dechiffrer(donnees: bytes, cle_: bytes) -> bytes:
    if not donnees.startswith(ENTETE):
        raise ValueError("Ce fichier n'est pas une sauvegarde Jarvis")
    nonce = donnees[len(ENTETE):len(ENTETE) + 12]
    return AESGCM(cle_).decrypt(nonce, donnees[len(ENTETE) + 12:], ENTETE)


def _copie_sqlite(source: Path) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        cible = Path(d) / "copie.sqlite"
        src = sqlite3.connect(source)
        dst = sqlite3.connect(cible)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return cible.read_bytes()


def sauvegarder(coffre, destination: Path, donnees: Path | None = None, garder: int = 14) -> Path:
    donnees = donnees or chemins.dossier_donnees()
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for nom in FICHIERS:
            source = donnees / nom
            if not source.exists():
                continue
            z.writestr(nom, _copie_sqlite(source) if nom.endswith(".sqlite") else source.read_bytes())
    destination.mkdir(parents=True, exist_ok=True)
    fichier = destination / f"jarvis-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sauv"
    fichier.write_bytes(chiffrer(tampon.getvalue(), cle(coffre)))
    for ancien in sorted(destination.glob("jarvis-*.sauv"))[:-garder]:
        ancien.unlink()
    return fichier


def restaurer(fichier: Path, cle_: bytes, cible: Path) -> list[str]:
    contenu = dechiffrer(fichier.read_bytes(), cle_)
    cible.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        z.extractall(cible)
        return z.namelist()
