"""Interface d'un outil (« une main » de Jarvis). Un outil = un module, sans toucher au cœur.

Pour ajouter un outil : créer une sous-classe d'`Outil` dans un module de `jarvis/outils/` (ou
dans le dossier `outils_perso` des données) et l'ajouter à la liste `OUTILS` du module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from urllib.parse import urlparse

import httpx

from jarvis.securite.reseau import GARDE, _correspond


class Niveau(IntEnum):
    """SEC-01."""

    LECTURE = 0  # libre
    REVERSIBLE = 1  # libre, annoncée
    IRREVERSIBLE = 2  # irréversible ou sortante : toujours confirmée

    @property
    def nom_fr(self) -> str:
        return ("lecture", "reversible", "irreversible")[self]


@dataclass
class Resultat:
    ok: bool
    message: str  # ce que le modèle lit (court, factuel)
    donnees: Any = None  # pour l'interface
    verifie: bool | None = None  # BRN-04 : rempli par `verifier`
    contenu_externe: bool = False  # SEC-02 : le message contient du contenu lu (web, mail…)

    @classmethod
    def echec(cls, message: str) -> Resultat:
        return cls(False, message)


@dataclass
class Contexte:
    """Ce que l'orchestrateur fournit à un outil pendant son exécution."""

    config: Any = None
    coffre: Any = None
    memoire: Any = None
    services: dict = field(default_factory=dict)  # rappels, client LLM, vision, etc.
    origine: str = "texte"
    outil: Outil | None = None

    async def http(self, methode: str, url: str, **kwargs) -> httpx.Response:
        """Requête HTTP limitée aux hôtes déclarés par l'outil (SEC-04)."""
        outil = self.outil
        hotes = outil.hotes if outil else ()
        hote = (urlparse(url).hostname or "").lower()
        if not _correspond(hote, hotes) and hote not in ("127.0.0.1", "localhost"):
            raise PermissionError(f"L'outil {outil.nom if outil else '?'} n'a pas déclaré l'hôte {hote}")

        def envoyer() -> httpx.Response:
            with GARDE.pour_outil(outil.nom if outil else "?", hotes), \
                    httpx.Client(timeout=kwargs.pop("timeout", 20), follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (Jarvis, assistant personnel)"}) as client:
                return client.request(methode, url, **kwargs)

        return await asyncio.to_thread(envoyer)


class Outil:
    nom: str = ""
    description: str = ""
    parametres: dict = {"type": "object", "properties": {}}
    niveau: Niveau = Niveau.LECTURE
    hotes: tuple[str, ...] = ()  # sorties réseau autorisées (SEC-04)
    lit_contenu_externe: bool = False  # SEC-02
    windows_seulement: bool = False

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.nom, "description": self.description,
                                                 "parameters": self.parametres}}

    def decrire(self, args: dict) -> str:
        """Phrase lue à Mathieu pour une annonce ou une confirmation."""
        details = ", ".join(f"{k} = {v}" for k, v in args.items())
        return f"{self.nom} ({details})" if details else self.nom

    async def executer(self, ctx: Contexte, **args) -> Resultat:  # pragma: no cover - interface
        raise NotImplementedError

    async def verifier(self, ctx: Contexte, args: dict, resultat: Resultat) -> bool | None:
        """BRN-04 : l'action a-t-elle eu l'effet attendu ? None si invérifiable."""
        return None
