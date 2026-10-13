"""Téléchargement vérifié des modèles et outils.

Un téléchargement *récupère* un fichier public ; il n'envoie aucune donnée de Mathieu.
Garde-fous :
- seuls les hôtes de la liste blanche sont contactés, redirections comprises ;
- chaque fichier est vérifié (taille et SHA-256 figés dans le catalogue) avant usage ;
- reprise d'un téléchargement interrompu (en-tête Range), écriture atomique.
"""

from __future__ import annotations

import hashlib
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

HOTES_AUTORISES = (
    "github.com",
    "githubusercontent.com",  # release-assets / objects
    "huggingface.co",
    "hf.co",  # CDN et stockage xet de Hugging Face
)

TAILLE_BLOC = 1024 * 1024


class TelechargementRefuse(RuntimeError):
    """Hôte hors liste blanche, ou fichier dont l'empreinte ne correspond pas."""


def hote_autorise(url: str) -> bool:
    hote = (urlparse(url).hostname or "").lower()
    return any(hote == h or hote.endswith("." + h) for h in HOTES_AUTORISES)


class _RedirectionControlee(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not hote_autorise(newurl):
            raise TelechargementRefuse(f"Redirection vers un hôte non autorisé : {urlparse(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_ouvreur = urllib.request.build_opener(_RedirectionControlee)
_ouvreur.addheaders = [("User-Agent", "jarvis-diagnostic")]


@dataclass(frozen=True)
class Fichier:
    """Un fichier à récupérer : URL, destination relative, taille et empreinte attendues."""

    url: str
    destination: str  # chemin relatif au dossier cible
    taille: int
    sha256: str

    @property
    def nom(self) -> str:
        return Path(self.destination).name


def sha256_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        while bloc := f.read(TAILLE_BLOC * 8):
            h.update(bloc)
    return h.hexdigest()


def _afficher_progression(nom: str, fait: int, total: int, debut: float) -> None:
    duree = max(time.monotonic() - debut, 1e-6)
    pct = 100 * fait / total if total else 0
    debit = fait / duree / 1e6
    sys.stdout.write(f"\r  {nom} : {pct:5.1f} % ({fait / 1e9:.2f}/{total / 1e9:.2f} Go, {debit:.1f} Mo/s)")
    sys.stdout.flush()


def telecharger(fichier: Fichier, dossier: Path, verifier_existant: bool = True) -> Path:
    """Télécharge `fichier` dans `dossier` s'il manque, et le vérifie. Renvoie son chemin."""
    if not hote_autorise(fichier.url):
        raise TelechargementRefuse(f"Hôte non autorisé : {fichier.url}")
    cible = dossier / fichier.destination
    cible.parent.mkdir(parents=True, exist_ok=True)

    if cible.exists() and cible.stat().st_size == fichier.taille:
        if not verifier_existant or sha256_fichier(cible) == fichier.sha256:
            return cible
        cible.unlink()  # présent mais corrompu : on le refait

    partiel = cible.with_name(cible.name + ".partiel")
    deja = partiel.stat().st_size if partiel.exists() else 0
    if deja > fichier.taille:
        partiel.unlink()
        deja = 0

    requete = urllib.request.Request(fichier.url)
    if deja:
        requete.add_header("Range", f"bytes={deja}-")
    debut = time.monotonic()
    with _ouvreur.open(requete, timeout=60) as reponse:
        if deja and reponse.status != 206:  # le serveur ignore la reprise : on repart de zéro
            deja = 0
        with open(partiel, "ab" if deja else "wb") as sortie:
            fait = deja
            dernier_affichage = 0.0
            while bloc := reponse.read(TAILLE_BLOC):
                sortie.write(bloc)
                fait += len(bloc)
                if time.monotonic() - dernier_affichage > 0.5:
                    _afficher_progression(fichier.nom, fait, fichier.taille, debut)
                    dernier_affichage = time.monotonic()
    _afficher_progression(fichier.nom, fichier.taille, fichier.taille, debut)
    sys.stdout.write("\n")

    taille = partiel.stat().st_size
    if taille != fichier.taille:
        raise TelechargementRefuse(f"{fichier.nom} : taille {taille} au lieu de {fichier.taille}")
    empreinte = sha256_fichier(partiel)
    if empreinte != fichier.sha256:
        partiel.unlink()
        raise TelechargementRefuse(f"{fichier.nom} : empreinte SHA-256 inattendue ({empreinte})")
    partiel.replace(cible)
    return cible
