"""Journal des actions (SEC-03) : chaque exécution d'outil, avec la demande qui l'a provoquée.

SQLite local. Consultable par l'interface (`/api/journal`) et par l'outil « journal_actions ».
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from jarvis import chemins

_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,
    conversation TEXT,
    origine TEXT,            -- voix, texte, routine, initiative, tache
    demande TEXT,            -- ce que Mathieu a dit ou écrit
    outil TEXT NOT NULL,
    arguments TEXT,
    niveau TEXT,             -- lecture, reversible, irreversible
    decision TEXT,           -- libre, annoncee, confirmee, refusee, bloquee
    ok INTEGER,
    verifie INTEGER,         -- 1 vérifié, 0 échec de vérification, NULL non vérifiable
    resultat TEXT,
    suite_contenu_externe INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS actions_date ON actions(horodatage);
"""


class Journal:
    def __init__(self, chemin: Path | None = None):
        self.chemin = chemin or chemins.dossier_donnees() / "journal.sqlite"
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.Lock()
        self._cnx = sqlite3.connect(self.chemin, check_same_thread=False)
        self._cnx.executescript(_SCHEMA)

    def consigner(self, *, outil: str, arguments: dict, niveau: str, decision: str, demande: str = "",
                  origine: str = "", conversation: str = "", ok: bool | None = None, verifie: bool | None = None,
                  resultat: str = "", suite_contenu_externe: bool = False) -> int:
        with self._verrou, self._cnx:
            curseur = self._cnx.execute(
                "INSERT INTO actions (horodatage, conversation, origine, demande, outil, arguments, niveau, decision,"
                " ok, verifie, resultat, suite_contenu_externe) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), conversation, origine, demande, outil,
                 json.dumps(arguments, ensure_ascii=False), niveau, decision,
                 None if ok is None else int(ok), None if verifie is None else int(verifie), resultat[:4000],
                 int(suite_contenu_externe)),
            )
            return int(curseur.lastrowid)

    def dernieres(self, n: int = 50, outil: str | None = None) -> list[dict]:
        requete = "SELECT * FROM actions"
        params: tuple = ()
        if outil:
            requete += " WHERE outil = ?"
            params = (outil,)
        requete += " ORDER BY id DESC LIMIT ?"
        with self._verrou:
            curseur = self._cnx.execute(requete, (*params, n))
            colonnes = [c[0] for c in curseur.description]
            return [dict(zip(colonnes, ligne, strict=True)) for ligne in curseur.fetchall()]

    def fermer(self) -> None:
        self._cnx.close()
