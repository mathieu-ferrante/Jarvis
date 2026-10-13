"""Service de rappels et minuteurs (OUT-REM), persistant (SQLite), avec récurrences simples."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from jarvis import chemins

log = logging.getLogger(__name__)

RECURRENCES = ("aucune", "quotidienne", "jours_ouvres", "hebdomadaire", "mensuelle")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rappels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texte TEXT NOT NULL,
    quand TEXT NOT NULL,
    recurrence TEXT DEFAULT 'aucune',
    type TEXT DEFAULT 'rappel',   -- rappel ou minuteur
    actif INTEGER DEFAULT 1,
    cree TEXT
);
"""


def prochaine(quand: datetime, recurrence: str) -> datetime | None:
    if recurrence == "quotidienne":
        return quand + timedelta(days=1)
    if recurrence == "jours_ouvres":
        suivant = quand + timedelta(days=1)
        while suivant.weekday() >= 5:
            suivant += timedelta(days=1)
        return suivant
    if recurrence == "hebdomadaire":
        return quand + timedelta(weeks=1)
    if recurrence == "mensuelle":
        mois = quand.month % 12 + 1
        annee = quand.year + (quand.month == 12)
        jour = min(quand.day, 28)
        return quand.replace(year=annee, month=mois, day=jour)
    return None


def lire_date(texte: str) -> datetime:
    texte = texte.strip().replace("Z", "")
    moment = datetime.fromisoformat(texte)
    return moment.replace(tzinfo=None)


class ServiceRappels:
    def __init__(self, chemin: Path | None = None, bus=None):
        self.chemin = chemin or chemins.dossier_donnees() / "rappels.sqlite"
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._verrou = threading.Lock()
        self._cnx = sqlite3.connect(self.chemin, check_same_thread=False)
        self._cnx.row_factory = sqlite3.Row
        self._cnx.executescript(_SCHEMA)

    def ajouter(self, texte: str, quand: datetime, recurrence: str = "aucune", type_: str = "rappel") -> int:
        if recurrence not in RECURRENCES:
            raise ValueError(f"Récurrence inconnue : {recurrence}")
        with self._verrou, self._cnx:
            c = self._cnx.execute("INSERT INTO rappels (texte, quand, recurrence, type, cree) VALUES (?,?,?,?,?)",
                                  (texte, quand.isoformat(timespec="seconds"), recurrence, type_,
                                   datetime.now().isoformat(timespec="seconds")))
            return int(c.lastrowid)

    def lister(self, actifs: bool = True) -> list[dict]:
        with self._verrou:
            return [dict(r) for r in self._cnx.execute(
                "SELECT * FROM rappels" + (" WHERE actif = 1" if actifs else "") + " ORDER BY quand")]

    def annuler(self, ident: int) -> bool:
        with self._verrou, self._cnx:
            return self._cnx.execute("UPDATE rappels SET actif = 0 WHERE id = ? AND actif = 1", (ident,)).rowcount > 0

    def echus(self, maintenant: datetime | None = None) -> list[dict]:
        """Rappels arrivés à échéance ; les récurrents sont replanifiés, les autres désactivés."""
        maintenant = maintenant or datetime.now()
        sortie = []
        with self._verrou, self._cnx:
            for r in self._cnx.execute("SELECT * FROM rappels WHERE actif = 1 AND quand <= ?",
                                       (maintenant.isoformat(timespec="seconds"),)).fetchall():
                sortie.append(dict(r))
                suivant = prochaine(lire_date(r["quand"]), r["recurrence"])
                while suivant and suivant <= maintenant:
                    suivant = prochaine(suivant, r["recurrence"])
                if suivant:
                    self._cnx.execute("UPDATE rappels SET quand = ? WHERE id = ?",
                                      (suivant.isoformat(timespec="seconds"), r["id"]))
                else:
                    self._cnx.execute("UPDATE rappels SET actif = 0 WHERE id = ?", (r["id"],))
        return sortie

    async def boucle(self, intervalle: float = 1.0) -> None:
        while True:
            for r in self.echus():
                titre = "Minuteur terminé" if r["type"] == "minuteur" else "Rappel"
                log.info("%s : %s", titre, r["texte"])
                if self.bus:
                    self.bus.notifier(titre, r["texte"], urgent=True, categorie="rappel")
            await asyncio.sleep(intervalle)
