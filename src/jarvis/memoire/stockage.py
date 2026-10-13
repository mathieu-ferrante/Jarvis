"""Mémoire à long terme (lot J4) : faits sur Mathieu, historique des conversations, documents indexés.

- MEM-01 : chaque fait a une date et une source ;
- MEM-02 : recherche hybride (plongements locaux + plein texte SQLite FTS5) ;
- MEM-03 : lister ce que Jarvis sait sur un sujet, corriger, oublier (suppression réelle) ;
- MEM-04 : historique des conversations, cherchable.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import numpy as np

from jarvis import chemins
from jarvis.memoire.vecteurs import PlongeurAvecRepli, PlongeurHachage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS faits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texte TEXT NOT NULL,
    categorie TEXT DEFAULT 'general',
    source TEXT,
    cree TEXT NOT NULL,
    modifie TEXT NOT NULL,
    vecteur BLOB,
    plongeur TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS faits_fts USING fts5(texte, content='faits', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS faits_ai AFTER INSERT ON faits BEGIN
    INSERT INTO faits_fts(rowid, texte) VALUES (new.id, new.texte); END;
CREATE TRIGGER IF NOT EXISTS faits_ad AFTER DELETE ON faits BEGIN
    INSERT INTO faits_fts(faits_fts, rowid, texte) VALUES ('delete', old.id, old.texte); END;
CREATE TRIGGER IF NOT EXISTS faits_au AFTER UPDATE OF texte ON faits BEGIN
    INSERT INTO faits_fts(faits_fts, rowid, texte) VALUES ('delete', old.id, old.texte);
    INSERT INTO faits_fts(rowid, texte) VALUES (new.id, new.texte); END;

CREATE TABLE IF NOT EXISTS echanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,
    conversation TEXT,
    canal TEXT,
    demande TEXT,
    reponse TEXT,
    actions TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS echanges_fts USING fts5(demande, reponse, content='echanges', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS echanges_ai AFTER INSERT ON echanges BEGIN
    INSERT INTO echanges_fts(rowid, demande, reponse) VALUES (new.id, new.demande, new.reponse); END;
CREATE TRIGGER IF NOT EXISTS echanges_ad AFTER DELETE ON echanges BEGIN
    INSERT INTO echanges_fts(echanges_fts, rowid, demande, reponse) VALUES ('delete', old.id, old.demande, old.reponse); END;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chemin TEXT NOT NULL,
    morceau INTEGER NOT NULL,
    texte TEXT NOT NULL,
    modifie REAL,
    vecteur BLOB,
    plongeur TEXT
);
CREATE INDEX IF NOT EXISTS documents_chemin ON documents(chemin);
"""

SEUIL_DOUBLON = 0.92
SEUIL_CONTEXTE = 0.45


def _requete_fts(texte: str) -> str:
    mots = [m for m in re.findall(r"\w+", texte.lower()) if len(m) > 2]
    return " OR ".join(f'"{m}"' for m in mots[:12])


class Memoire:
    def __init__(self, chemin: Path | str | None = None, plongeur=None):
        self.chemin = Path(chemin) if chemin else chemins.dossier_donnees() / "memoire.sqlite"
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.plongeur = plongeur or PlongeurAvecRepli(None)
        self._verrou = threading.RLock()
        self._cnx = sqlite3.connect(self.chemin, check_same_thread=False)
        self._cnx.row_factory = sqlite3.Row
        self._cnx.executescript(_SCHEMA)
        self._cache_vecteurs: dict[str, tuple[str, list[int], np.ndarray]] = {}  # PERF-13

    def _invalider(self, table: str) -> None:
        self._cache_vecteurs.pop(table, None)

    # --- Plongements ------------------------------------------------------------------------

    def _plonger(self, textes: list[str], requete: bool = False) -> tuple[np.ndarray, str]:
        if isinstance(self.plongeur, PlongeurAvecRepli):
            return self.plongeur.plonger(textes, requete)
        if isinstance(self.plongeur, PlongeurHachage):
            return self.plongeur.plonger(textes), self.plongeur.identifiant
        return self.plongeur.plonger(textes, requete), self.plongeur.identifiant

    def _vecteurs_table(self, table: str, identifiant: str) -> tuple[list[int], np.ndarray]:
        """Vecteurs d'une table, gardés en mémoire (une matrice) et recalculés si le modèle a changé."""
        cache = self._cache_vecteurs.get(table)
        if cache and cache[0] == identifiant:
            return cache[1], cache[2]
        ids, matrice = self._charger_vecteurs(table, identifiant)
        self._cache_vecteurs[table] = (identifiant, ids, matrice)
        return ids, matrice

    def _charger_vecteurs(self, table: str, identifiant: str) -> tuple[list[int], np.ndarray]:
        lignes = self._cnx.execute(f"SELECT id, texte, vecteur, plongeur FROM {table}").fetchall()
        a_refaire = [r for r in lignes if r["plongeur"] != identifiant or r["vecteur"] is None]
        if a_refaire:
            vecteurs, ident = self._plonger([r["texte"] for r in a_refaire])
            with self._cnx:
                for r, v in zip(a_refaire, vecteurs, strict=True):
                    self._cnx.execute(f"UPDATE {table} SET vecteur = ?, plongeur = ? WHERE id = ?",
                                      (v.tobytes(), ident, r["id"]))
            lignes = self._cnx.execute(f"SELECT id, texte, vecteur, plongeur FROM {table}").fetchall()
        lignes = [r for r in lignes if r["vecteur"] is not None]
        if not lignes:
            return [], np.zeros((0, 1), dtype=np.float32)
        return [r["id"] for r in lignes], np.stack([np.frombuffer(r["vecteur"], dtype=np.float32) for r in lignes])

    # --- Faits (MEM-01, MEM-03) -------------------------------------------------------------

    def memoriser(self, texte: str, source: str = "conversation", categorie: str = "general") -> dict:
        """Enregistre un fait. Un fait quasi identique existant est mis à jour plutôt que doublé."""
        texte = texte.strip()
        maintenant = datetime.now().isoformat(timespec="seconds")
        with self._verrou:
            proches = self.rechercher(texte, n=1, seuil=SEUIL_DOUBLON, plein_texte=False)
            vecteur, ident = self._plonger([texte])
            self._invalider("faits")  # après la recherche ci-dessus, qui a rempli le cache
            with self._cnx:
                if proches:
                    self._cnx.execute("UPDATE faits SET texte = ?, source = ?, modifie = ?, vecteur = ?, plongeur = ? "
                                      "WHERE id = ?", (texte, source, maintenant, vecteur[0].tobytes(), ident,
                                                       proches[0]["id"]))
                    return {"id": proches[0]["id"], "mis_a_jour": True}
                curseur = self._cnx.execute(
                    "INSERT INTO faits (texte, categorie, source, cree, modifie, vecteur, plongeur) VALUES (?,?,?,?,?,?,?)",
                    (texte, categorie, source, maintenant, maintenant, vecteur[0].tobytes(), ident))
                return {"id": curseur.lastrowid, "mis_a_jour": False}

    def rechercher(self, requete: str, n: int = 5, seuil: float = 0.3, plein_texte: bool = True) -> list[dict]:
        """Recherche hybride : similarité des plongements, complétée par le plein texte."""
        with self._verrou:
            q, ident = self._plonger([requete], requete=True)
            ids, vecteurs = self._vecteurs_table("faits", ident)
            scores: dict[int, float] = {}
            if ids:
                for i, s in zip(ids, vecteurs @ q[0], strict=True):
                    if s >= seuil:
                        scores[i] = float(s)
            if plein_texte and (fts := _requete_fts(requete)):
                for r in self._cnx.execute("SELECT rowid FROM faits_fts WHERE faits_fts MATCH ? LIMIT 20", (fts,)):
                    scores[r[0]] = max(scores.get(r[0], 0.0), seuil + 0.05)
            meilleurs = sorted(scores.items(), key=lambda kv: -kv[1])[:n]
            resultat = []
            for i, s in meilleurs:
                r = self._cnx.execute("SELECT * FROM faits WHERE id = ?", (i,)).fetchone()
                if r:
                    resultat.append({"id": r["id"], "texte": r["texte"], "source": r["source"], "cree": r["cree"],
                                     "modifie": r["modifie"], "categorie": r["categorie"], "score": round(s, 3)})
            return resultat

    def rappeler_pour_contexte(self, texte: str, n: int = 3) -> list[str]:
        return [f"{f['texte']} (noté le {f['modifie'][:10]})" for f in self.rechercher(texte, n=n, seuil=SEUIL_CONTEXTE)]

    def lister(self, sujet: str | None = None, n: int = 50) -> list[dict]:
        if sujet:
            return self.rechercher(sujet, n=n, seuil=0.25)
        with self._verrou:
            return [dict(r) | {"vecteur": None} for r in
                    self._cnx.execute("SELECT id, texte, source, cree, modifie, categorie FROM faits ORDER BY modifie DESC "
                                      "LIMIT ?", (n,))]

    def corriger(self, ident: int, texte: str) -> bool:
        self._invalider("faits")
        vecteur, plongeur = self._plonger([texte])
        with self._verrou, self._cnx:
            c = self._cnx.execute("UPDATE faits SET texte = ?, modifie = ?, vecteur = ?, plongeur = ? WHERE id = ?",
                                  (texte, datetime.now().isoformat(timespec="seconds"), vecteur[0].tobytes(), plongeur,
                                   ident))
            return c.rowcount > 0

    def oublier(self, ident: int) -> bool:
        """Suppression réelle (et non un simple masquage), y compris de l'index plein texte."""
        self._invalider("faits")
        with self._verrou, self._cnx:
            c = self._cnx.execute("DELETE FROM faits WHERE id = ?", (ident,))
        if c.rowcount:
            with self._verrou:
                self._cnx.execute("VACUUM")
        return c.rowcount > 0

    def fait(self, ident: int) -> dict | None:
        with self._verrou:
            r = self._cnx.execute("SELECT id, texte, source, cree, modifie FROM faits WHERE id = ?", (ident,)).fetchone()
            return dict(r) if r else None

    # --- Historique (MEM-04) ----------------------------------------------------------------

    def historiser(self, conversation: str, canal: str, demande: str, reponse: str, actions: list | None = None) -> None:
        with self._verrou, self._cnx:
            self._cnx.execute("INSERT INTO echanges (horodatage, conversation, canal, demande, reponse, actions) "
                              "VALUES (?,?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), conversation, canal,
                                                      demande, reponse, json.dumps(actions or [], ensure_ascii=False)))

    def historique(self, n: int = 50, conversation: str | None = None) -> list[dict]:
        requete = "SELECT * FROM echanges" + (" WHERE conversation = ?" if conversation else "") + " ORDER BY id DESC LIMIT ?"
        params = (conversation, n) if conversation else (n,)
        with self._verrou:
            return [dict(r) for r in self._cnx.execute(requete, params)]

    def chercher_historique(self, requete: str, n: int = 10) -> list[dict]:
        fts = _requete_fts(requete)
        if not fts:
            return []
        with self._verrou:
            return [dict(r) for r in self._cnx.execute(
                "SELECT e.* FROM echanges_fts f JOIN echanges e ON e.id = f.rowid WHERE echanges_fts MATCH ? "
                "ORDER BY rank LIMIT ?", (fts, n))]

    def effacer_historique(self, avant: str | None = None) -> int:
        with self._verrou, self._cnx:
            if avant:
                c = self._cnx.execute("DELETE FROM echanges WHERE horodatage < ?", (avant,))
            else:
                c = self._cnx.execute("DELETE FROM echanges")
        return c.rowcount

    # --- Documents (MEM-02) -----------------------------------------------------------------

    def indexer_texte(self, chemin: str, texte: str, modifie: float, taille_morceau: int = 800) -> int:
        self._invalider("documents")
        morceaux = []
        paragraphe = ""
        for bloc in re.split(r"\n\s*\n", texte):
            if len(paragraphe) + len(bloc) > taille_morceau and paragraphe:
                morceaux.append(paragraphe.strip())
                paragraphe = ""
            paragraphe += bloc + "\n\n"
        if paragraphe.strip():
            morceaux.append(paragraphe.strip())
        morceaux = [m[:2000] for m in morceaux if m]
        if not morceaux:
            return 0
        vecteurs, ident = self._plonger(morceaux)
        with self._verrou, self._cnx:
            self._cnx.execute("DELETE FROM documents WHERE chemin = ?", (chemin,))
            self._cnx.executemany("INSERT INTO documents (chemin, morceau, texte, modifie, vecteur, plongeur) "
                                  "VALUES (?,?,?,?,?,?)",
                                  [(chemin, i, m, modifie, v.tobytes(), ident)
                                   for i, (m, v) in enumerate(zip(morceaux, vecteurs, strict=True))])
        return len(morceaux)

    def date_document(self, chemin: str) -> float | None:
        with self._verrou:
            r = self._cnx.execute("SELECT modifie FROM documents WHERE chemin = ? LIMIT 1", (chemin,)).fetchone()
            return r[0] if r else None

    def chercher_documents(self, requete: str, n: int = 5) -> list[dict]:
        with self._verrou:
            q, ident = self._plonger([requete], requete=True)
            ids, vecteurs = self._vecteurs_table("documents", ident)
            if not ids:
                return []
            scores = vecteurs @ q[0]
            ordre = np.argsort(-scores)[:n]
            resultat = []
            for k in ordre:
                r = self._cnx.execute("SELECT chemin, morceau, texte FROM documents WHERE id = ?", (ids[k],)).fetchone()
                resultat.append({"chemin": r["chemin"], "morceau": r["morceau"], "texte": r["texte"],
                                 "score": round(float(scores[k]), 3)})
            return resultat

    def statistiques(self) -> dict:
        with self._verrou:
            return {t: self._cnx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("faits", "echanges", "documents")}

    def sauvegarder_vers(self, destination: Path) -> None:
        """Copie cohérente de la base (API de sauvegarde SQLite)."""
        with self._verrou:
            cible = sqlite3.connect(destination)
            with cible:
                self._cnx.backup(cible)
            cible.close()

    def fermer(self) -> None:
        self._cnx.close()
