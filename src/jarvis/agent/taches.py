"""Tâches de fond (BRN-03, INI-02) : une demande longue tourne à part et notifie à la fin."""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass
class TacheFond:
    id: int
    objectif: str
    debut: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    etat: str = "en_cours"  # en_cours, terminee, echec, annulee
    resultat: str = ""
    tache: asyncio.Task | None = None


class GestionnaireTaches:
    def __init__(self, orchestrateur):
        self.orchestrateur = orchestrateur
        self.taches: dict[int, TacheFond] = {}
        self._ids = itertools.count(1)

    def lancer(self, objectif: str) -> TacheFond:
        t = TacheFond(next(self._ids), objectif)
        t.tache = asyncio.create_task(self._executer(t))
        self.taches[t.id] = t
        self.orchestrateur.bus.publier("tache", id=t.id, objectif=objectif, etat="en_cours")
        return t

    async def _executer(self, t: TacheFond) -> None:
        consigne = (f"Tâche de fond : {t.objectif}\nTravaille étape par étape avec les outils, puis termine par "
                    "un compte rendu factuel et concis de ce qui a été fait et trouvé (ou de ce qui a échoué).")
        try:
            t.resultat = await self.orchestrateur.repondre_texte(
                consigne, canal="texte", conversation=f"tache-{t.id}", origine="tache")
            t.etat = "terminee"
        except asyncio.CancelledError:
            t.etat = "annulee"
            t.resultat = "Tâche annulée."
        except Exception as e:  # noqa: BLE001
            log.exception("Tâche %s en échec", t.id)
            t.etat, t.resultat = "echec", f"Échec : {e}"
        bus = self.orchestrateur.bus
        bus.publier("tache", id=t.id, objectif=t.objectif, etat=t.etat, resultat=t.resultat)
        if t.etat != "annulee":
            bus.notifier(f"Tâche terminée : {t.objectif[:60]}", t.resultat[:500], categorie="tache")

    def annuler_tout(self) -> None:
        for t in self.taches.values():
            if t.tache and not t.tache.done():
                t.tache.cancel()

    def liste(self) -> list[dict]:
        return [{"id": t.id, "objectif": t.objectif, "debut": t.debut, "etat": t.etat, "resultat": t.resultat[:300]}
                for t in self.taches.values()]
