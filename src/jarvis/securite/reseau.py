"""Garde réseau (SEC-04) : liste blanche des sorties, appliquée à tout le processus.

Un crochet d'audit Python (`sys.addaudithook`) intercepte chaque résolution DNS et chaque
connexion sortante. Sont autorisés : la boucle locale, le réseau privé Tailscale (100.64/10)
et, uniquement pendant l'exécution d'un outil, les hôtes que cet outil déclare. Tout le reste
est refusé et consigné. Les modules du cœur (voix, cerveau, mémoire) n'ont donc aucune sortie.

Limite assumée : un programme externe lancé par un outil (navigateur, PowerShell) n'est pas
couvert par ce crochet ; ces outils sont soumis aux permissions (SEC-01).
"""

from __future__ import annotations

import contextlib
import contextvars
import ipaddress
import logging
import socket
import sys
import threading
from collections.abc import Iterator

log = logging.getLogger(__name__)

_outil_courant: contextvars.ContextVar[tuple[str, tuple[str, ...]] | None] = contextvars.ContextVar(
    "outil_courant", default=None)


class SortieRefusee(PermissionError):
    pass


def _est_local(hote: str) -> bool:
    hote = hote.strip("[]").lower()
    if hote in ("localhost", "") or hote.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(hote.split("%")[0])
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")  # Tailscale (CGNAT)


def _correspond(hote: str, motifs: tuple[str, ...]) -> bool:
    hote = hote.lower().rstrip(".")
    return any(hote == m or hote.endswith("." + m) or m == "*" for m in motifs)


class GardeReseau:
    def __init__(self):
        self.actif = False
        self.refus: list[dict] = []
        self._ips_autorisees: dict[str, str] = {}  # ip -> outil qui l'a résolue
        self._verrou = threading.Lock()
        self._dans_crochet = threading.local()

    # API ----------------------------------------------------------------------------------

    @contextlib.contextmanager
    def pour_outil(self, nom: str, hotes: tuple[str, ...]) -> Iterator[None]:
        """Pendant ce bloc, les hôtes déclarés par l'outil sont joignables."""
        jeton = _outil_courant.set((nom, tuple(h.lower() for h in hotes)))
        try:
            yield
        finally:
            _outil_courant.reset(jeton)

    def installer(self) -> None:
        if not self.actif:
            sys.addaudithook(self._crochet)
            self.actif = True

    # Crochet ------------------------------------------------------------------------------

    def _refuser(self, hote: str, motif: str) -> None:
        contexte = _outil_courant.get()
        entree = {"hote": hote, "outil": contexte[0] if contexte else None, "motif": motif}
        with self._verrou:
            self.refus.append(entree)
            del self.refus[:-200]
        log.warning("Sortie réseau refusée : %s", entree)
        raise SortieRefusee(f"Sortie réseau refusée vers {hote} ({motif}) — SEC-04")

    def _crochet(self, evenement: str, args: tuple) -> None:
        if evenement not in ("socket.getaddrinfo", "socket.connect"):
            return
        if getattr(self._dans_crochet, "oui", False):
            return
        if evenement == "socket.getaddrinfo":
            hote = str(args[0]) if args and args[0] is not None else ""
            if _est_local(hote):
                return
            contexte = _outil_courant.get()
            if not contexte or not _correspond(hote, contexte[1]):
                self._refuser(hote, f"hôte non déclaré par {'l’outil ' + contexte[0] if contexte else 'le cœur'}")
            # Résolution autorisée : on retient les adresses pour la connexion qui suit
            self._dans_crochet.oui = True
            try:
                for info in socket.getaddrinfo(hote, None):
                    self._ips_autorisees[info[4][0]] = contexte[0]
            except OSError:
                pass
            finally:
                self._dans_crochet.oui = False
            return
        # socket.connect : (socket, adresse)
        adresse = args[1] if len(args) > 1 else None
        if not isinstance(adresse, tuple) or not adresse:
            return  # socket AF_UNIX ou autre
        ip = str(adresse[0])
        if _est_local(ip):
            return
        contexte = _outil_courant.get()
        if ip in self._ips_autorisees and contexte is not None:
            return
        if contexte and _correspond(ip, contexte[1]):  # IP déclarée telle quelle (ex. Home Assistant)
            return
        self._refuser(ip, "adresse non résolue par un outil autorisé")


GARDE = GardeReseau()
