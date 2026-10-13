"""Rappels selon le contexte (INI-11, lot J15) : lieu, appareil, fin de partie.

- lieu : « quand je passe à la boulangerie » — la position du téléphone n'est demandée que s'il
  existe au moins un rappel de lieu, toutes les 5 minutes, et seulement si Mathieu a activé le
  partage de position dans l'appli (TEL-06). Rien n'est conservé au-delà de la comparaison.
- appareil : « quand je suis sur le Mac » — déclenché quand cet appareil devient actif.
- fin_partie : « après ma partie » — déclenché à la sortie du mode jeu.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from jarvis import chemins

log = logging.getLogger(__name__)
INTERVALLE_POSITION_S = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rappels_contexte (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texte TEXT NOT NULL,
    type TEXT NOT NULL,          -- lieu, appareil, fin_partie
    condition TEXT NOT NULL,     -- JSON : {lat, lon, rayon_m, nom} | {appareil} | {}
    recurrent INTEGER DEFAULT 0,
    actif INTEGER DEFAULT 1,
    cree TEXT
);
"""


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau (haversine), en mètres."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def lire_position(message: str) -> tuple[float, float] | None:
    """Analyse « Position : 43.296, 5.370 (précision ~100 m). » renvoyé par l'outil du téléphone."""
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*,\s*(-?\d+(?:[.,]\d+)?)", message)
    if not m:
        return None
    return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))


class RappelsContexte:
    def __init__(self, chemin: Path | None = None, bus=None):
        self.chemin = chemin or chemins.dossier_donnees() / "rappels.sqlite"
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._verrou = threading.Lock()
        self._cnx = sqlite3.connect(self.chemin, check_same_thread=False)
        self._cnx.row_factory = sqlite3.Row
        self._cnx.executescript(_SCHEMA)

    def ajouter(self, texte: str, type_: str, condition: dict, recurrent: bool = False) -> int:
        if type_ not in ("lieu", "appareil", "fin_partie"):
            raise ValueError(type_)
        with self._verrou, self._cnx:
            c = self._cnx.execute("INSERT INTO rappels_contexte (texte, type, condition, recurrent, cree) VALUES (?,?,?,?,?)",
                                  (texte, type_, json.dumps(condition, ensure_ascii=False), int(recurrent),
                                   datetime.now().isoformat(timespec="seconds")))
            return int(c.lastrowid)

    def lister(self, type_: str | None = None) -> list[dict]:
        with self._verrou:
            lignes = self._cnx.execute("SELECT * FROM rappels_contexte WHERE actif = 1" +
                                       (" AND type = ?" if type_ else ""), (type_,) if type_ else ()).fetchall()
        return [{**dict(r), "condition": json.loads(r["condition"])} for r in lignes]

    def annuler(self, ident: int) -> bool:
        with self._verrou, self._cnx:
            return self._cnx.execute("UPDATE rappels_contexte SET actif = 0 WHERE id = ?", (ident,)).rowcount > 0

    def _declencher(self, rappel: dict, raison: str) -> None:
        if not rappel["recurrent"]:
            self.annuler(rappel["id"])
        log.info("Rappel contextuel (%s) : %s", raison, rappel["texte"])
        if self.bus:
            self.bus.notifier("Rappel", f"{rappel['texte']} ({raison})", urgent=True, categorie="rappel")

    # --- Déclencheurs ---------------------------------------------------------------------

    def sur_evenement(self, evt) -> None:
        """Abonné au bus : fin de partie, appareil devenu actif."""
        if evt.type == "jeu" and evt.donnees.get("etat") == "inactif":
            for r in self.lister("fin_partie"):
                self._declencher(r, "fin de partie")
        if evt.type == "appareil" and evt.donnees.get("etat") == "connecte":
            nom = (evt.donnees.get("nom") or "").lower()
            for r in self.lister("appareil"):
                cible = r["condition"].get("appareil", "").lower()
                if cible and (cible in nom or nom in cible):
                    self._declencher(r, f"sur {evt.donnees.get('nom')}")

    def verifier_position(self, lat: float, lon: float) -> list[dict]:
        declenches = []
        for r in self.lister("lieu"):
            c = r["condition"]
            if distance_m(lat, lon, c["lat"], c["lon"]) <= c.get("rayon_m", 150):
                self._declencher(r, f"près de {c.get('nom', 'ce lieu')}")
                declenches.append(r)
        return declenches

    async def boucle_position(self, demander_position) -> None:
        """`demander_position()` → (lat, lon) ou None (outil « position » du téléphone)."""
        while True:
            await asyncio.sleep(INTERVALLE_POSITION_S)
            if not self.lister("lieu"):
                continue  # aucun rappel de lieu : on ne demande rien au téléphone
            try:
                position = await demander_position()
            except Exception:  # noqa: BLE001
                position = None
            if position:
                self.verifier_position(*position)
