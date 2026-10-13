"""Coffre des secrets (SEC-05) : jetons et mots de passe chiffrés, hors du dépôt, jamais montrés au modèle.

Chiffrement par DPAPI de Windows (CryptProtectData, portée utilisateur) : seul le compte
Windows de Mathieu, sur ce PC, peut déchiffrer. Aucune clé n'est stockée en clair.
"""

from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

from jarvis import chemins

_ENTROPIE = b"jarvis-coffre-v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(donnees: bytes) -> _Blob:
    tampon = ctypes.create_string_buffer(donnees, len(donnees))
    return _Blob(len(donnees), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))


def _dpapi(donnees: bytes, chiffrer: bool) -> bytes:
    if sys.platform != "win32":
        raise OSError("Le coffre utilise DPAPI : Windows uniquement")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    entree, entropie, sortie = _blob(donnees), _blob(_ENTROPIE), _Blob()
    fonction = crypt32.CryptProtectData if chiffrer else crypt32.CryptUnprotectData
    args = (ctypes.byref(entree), None, ctypes.byref(entropie), None, None, 0x1, ctypes.byref(sortie))
    if chiffrer:
        args = (ctypes.byref(entree), "jarvis", ctypes.byref(entropie), None, None, 0x1, ctypes.byref(sortie))
    if not fonction(*args):
        raise OSError(f"DPAPI a échoué (code {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        kernel32.LocalFree(sortie.pbData)


def chiffrer(donnees: bytes) -> bytes:
    return _dpapi(donnees, True)


def dechiffrer(donnees: bytes) -> bytes:
    return _dpapi(donnees, False)


class Coffre:
    def __init__(self, chemin: Path | None = None):
        self.chemin = chemin or chemins.dossier_donnees() / "coffre.bin"

    def _lire(self) -> dict[str, str]:
        if not self.chemin.exists():
            return {}
        return json.loads(dechiffrer(self.chemin.read_bytes()).decode("utf-8"))

    def _ecrire(self, valeurs: dict[str, str]) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self.chemin.with_suffix(".tmp")
        temporaire.write_bytes(chiffrer(json.dumps(valeurs).encode("utf-8")))
        temporaire.replace(self.chemin)

    def lire(self, nom: str) -> str | None:
        return self._lire().get(nom)

    def ecrire(self, nom: str, valeur: str) -> None:
        valeurs = self._lire()
        valeurs[nom] = valeur
        self._ecrire(valeurs)

    def supprimer(self, nom: str) -> None:
        valeurs = self._lire()
        valeurs.pop(nom, None)
        self._ecrire(valeurs)

    def noms(self) -> list[str]:
        return sorted(self._lire())

    def masquer(self, texte: str) -> str:
        """Remplace toute valeur secrète présente dans `texte` (avant journal ou modèle)."""
        for valeur in self._lire().values():
            if valeur and len(valeur) >= 4:
                texte = texte.replace(valeur, "[secret masqué]")
        return texte
