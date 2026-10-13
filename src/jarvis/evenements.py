"""Bus d'évènements interne : notifications, états, confirmations, vers l'interface et la voix."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass
class Evenement:
    type: str  # notification, etat, confirmation, transcription, reponse, tache, journal…
    donnees: dict = field(default_factory=dict)
    horodatage: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class Bus:
    def __init__(self):
        self._abonnes: list[Callable[[Evenement], object]] = []
        self.historique: list[Evenement] = []

    def abonner(self, rappel: Callable[[Evenement], object]) -> Callable[[], None]:
        self._abonnes.append(rappel)
        return lambda: self._abonnes.remove(rappel) if rappel in self._abonnes else None

    def publier(self, type_: str, **donnees) -> Evenement:
        evt = Evenement(type_, donnees)
        self.historique.append(evt)
        del self.historique[:-500]
        for rappel in list(self._abonnes):
            try:
                resultat = rappel(evt)
                if asyncio.iscoroutine(resultat):
                    asyncio.ensure_future(resultat)
            except Exception:  # noqa: BLE001
                log.exception("Abonné en erreur pour %s", type_)
        return evt

    def notifier(self, titre: str, texte: str, urgent: bool = False, categorie: str = "info") -> Evenement:
        """Notification à Mathieu (interface, téléphone, et voix si elle n'est pas en mode jeu)."""
        return self.publier("notification", titre=titre, texte=texte, urgent=urgent, categorie=categorie)
