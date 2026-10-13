"""Permissions (SEC-01, SEC-02) et confirmations.

- lecture : libre ;
- action réversible : libre mais annoncée ; confirmée si elle découle d'un contenu lu (SEC-02) ;
- action irréversible ou sortante : toujours confirmée, avec le détail de l'action.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol

from jarvis.outils.base import Niveau, Outil


@dataclass
class Demande:
    outil: str
    description: str
    arguments: dict
    niveau: Niveau
    suite_contenu_externe: bool = False

    def question(self) -> str:
        source = " Cette action fait suite à un contenu lu, pas à ta demande directe." \
            if self.suite_contenu_externe else ""
        return f"Je dois {self.description}.{source} Tu confirmes ?"


class Confirmateur(Protocol):
    async def demander(self, demande: Demande) -> bool: ...


def decision(outil: Outil, suite_contenu_externe: bool) -> str:
    """« libre », « annoncer » ou « confirmer »."""
    if outil.niveau == Niveau.IRREVERSIBLE:
        return "confirmer"
    if outil.niveau == Niveau.REVERSIBLE:
        return "confirmer" if suite_contenu_externe else "annoncer"
    return "libre"


_OUI = re.compile(r"\b(oui|ouais|vas[- ]y|confirme|d'accord|ok|okay|c'est bon|valide|go)\b", re.I)
_NON = re.compile(r"\b(non|annule|stop|arr[eê]te|laisse tomber|surtout pas|pas question)\b", re.I)


def interpreter_reponse(texte: str) -> bool | None:
    """« oui » → True, « non » → False, ambigu → None. Le non l'emporte en cas de doute."""
    if _NON.search(texte):
        return False
    if _OUI.search(texte):
        return True
    return None


class ConfirmateurAutomatique:
    """Pour les tests : réponses prédéfinies."""

    def __init__(self, reponses: list[bool] | bool = False):
        self.reponses = reponses
        self.demandes: list[Demande] = []

    async def demander(self, demande: Demande) -> bool:
        self.demandes.append(demande)
        if isinstance(self.reponses, list):
            return self.reponses.pop(0) if self.reponses else False
        return self.reponses


class ConfirmateurFile:
    """Confirmation par l'interface (clic) ou par la voix : la demande est publiée, la réponse
    arrive par `repondre(id, oui)`. Sans réponse dans le délai : refus."""

    def __init__(self, publier, delai_s: float = 60):
        self.publier = publier  # callable(id, Demande)
        self.delai_s = delai_s
        self._attentes: dict[int, asyncio.Future] = {}
        self._compteur = 0

    async def demander(self, demande: Demande) -> bool:
        self._compteur += 1
        ident = self._compteur
        futur = asyncio.get_running_loop().create_future()
        self._attentes[ident] = futur
        await _appeler(self.publier, ident, demande)
        try:
            return bool(await asyncio.wait_for(futur, self.delai_s))
        except TimeoutError:
            return False
        finally:
            self._attentes.pop(ident, None)

    def repondre(self, ident: int, oui: bool) -> bool:
        futur = self._attentes.get(ident)
        if futur and not futur.done():
            futur.set_result(oui)
            return True
        return False

    def repondre_derniere(self, oui: bool) -> bool:
        if not self._attentes:
            return False
        return self.repondre(max(self._attentes), oui)

    @property
    def en_attente(self) -> bool:
        return bool(self._attentes)


async def _appeler(fonction, *args):
    resultat = fonction(*args)
    if asyncio.iscoroutine(resultat):
        await resultat
