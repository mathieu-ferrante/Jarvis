"""OUT-JEU : interroger le coach de jeux Postgame par son API locale (COM-07 de Postgame).

L'API de Postgame n'est pas encore figée : ce client découvre ses chemins dans `/openapi.json`
(fourni d'office par FastAPI) et se rabat sur des chemins PROVISOIRES sinon. Tout reste local
(127.0.0.1 ou le réseau Tailscale).
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from jarvis.outils.base import Contexte, Outil, Resultat

JEUX = ["cs2", "lol", "tft", "geometry_dash"]
# Chemins provisoires, utilisés si /openapi.json ne permet pas de les trouver
CHEMINS_PAR_DEFAUT = {
    "parties": "/api/parties",
    "partie": "/api/parties/{id}",
    "debrief": "/api/parties/{id}/debrief",
    "progression": "/api/progression",
}
MOTS_CLES = {
    "parties": ("parties", "matches", "games", "sessions"),
    "debrief": ("debrief",),
    "progression": ("progression", "progress", "tendances"),
}


def decouvrir_chemins(openapi: dict) -> dict[str, str]:
    """Associe nos besoins aux chemins réels de l'API Postgame d'après sa description OpenAPI."""
    chemins = dict(CHEMINS_PAR_DEFAUT)
    tous = [c for c, ops in (openapi.get("paths") or {}).items() if "get" in ops]
    for besoin, mots in MOTS_CLES.items():
        candidats = [c for c in tous if any(m in c.lower() for m in mots)]
        if besoin == "parties":
            liste = [c for c in candidats if "{" not in c]
            fiche = [c for c in candidats if re.search(r"\{[^}]+\}$", c) and "debrief" not in c]
            if liste:
                chemins["parties"] = min(liste, key=len)
            if fiche:
                chemins["partie"] = re.sub(r"\{[^}]+\}$", "{id}", min(fiche, key=len))
        elif candidats:
            chemins[besoin] = re.sub(r"\{[^}]+\}", "{id}", min(candidats, key=len))
    return chemins


class ClientPostgame:
    _cache_chemins: dict[str, dict] = {}

    def __init__(self, ctx: Contexte, outil: Outil):
        self.ctx = ctx
        self.base = ctx.config.integrations.postgame_url.rstrip("/")
        self.hote = urlparse(self.base).hostname or "127.0.0.1"
        self.outil = outil

    async def _get(self, chemin: str, **params):
        jeton = self.ctx.coffre.lire("postgame_jeton") if self.ctx.coffre else None
        entetes = {"Authorization": f"Bearer {jeton}"} if jeton else {}
        r = await self.ctx.http("GET", self.base + chemin, hotes=(self.hote,),
                                params={k: v for k, v in params.items() if v not in (None, "")}, headers=entetes)
        if r.status_code == 404:
            raise LookupError(chemin)
        r.raise_for_status()
        return r.json()

    async def chemins(self) -> dict[str, str]:
        if self.base not in self._cache_chemins:
            try:
                self._cache_chemins[self.base] = decouvrir_chemins(await self._get("/openapi.json"))
            except Exception:  # noqa: BLE001 — API non décrite : chemins provisoires
                self._cache_chemins[self.base] = dict(CHEMINS_PAR_DEFAUT)
        return self._cache_chemins[self.base]

    async def appel(self, besoin: str, ident: str | None = None, **params):
        chemin = (await self.chemins())[besoin].replace("{id}", str(ident or ""))
        return await self._get(chemin, **params)


def compacter(donnees, limite: int = 5000) -> str:
    """JSON lisible et borné pour le modèle (les mesures brutes peuvent être volumineuses)."""
    texte = json.dumps(donnees, ensure_ascii=False, indent=1, default=str)
    return texte if len(texte) <= limite else texte[:limite] + "\n… (tronqué)"


class StatistiquesJeu(Outil):
    nom = "statistiques_jeu"
    description = ("Interroge le coach de jeux Postgame : dernières parties ou sessions, mesures, progression, pour "
                   "CS2, LoL, TFT ou Geometry Dash. Réponds ensuite avec les vrais chiffres, sans en inventer.")
    parametres = {"type": "object", "properties": {
        "jeu": {"type": "string", "enum": JEUX},
        "mode": {"type": "string", "description": "Mode facultatif : deathmatch, premier, aram, ranked…"},
        "periode": {"type": "string", "enum": ["derniere_session", "jour", "semaine", "mois"]},
        "vue": {"type": "string", "enum": ["parties", "progression"], "description": "parties (défaut) ou progression."}},
        "required": ["jeu"]}
    hotes = ("127.0.0.1", "localhost")

    async def executer(self, ctx: Contexte, jeu: str, mode: str = "", periode: str = "derniere_session",
                       vue: str = "parties") -> Resultat:
        client = ClientPostgame(ctx, self)
        try:
            if vue == "progression":
                donnees = await client.appel("progression", jeu=jeu, mode=mode, periode=periode)
            else:
                limite = 1 if periode == "derniere_session" else 20
                donnees = await client.appel("parties", jeu=jeu, mode=mode, periode=periode, limite=limite)
        except LookupError:
            return Resultat.echec("Postgame répond, mais pas à ce chemin : son API a peut-être changé.")
        except Exception as e:  # noqa: BLE001
            return Resultat.echec(f"Postgame est injoignable ({type(e).__name__}) : est-il lancé ?")
        if not donnees:
            return Resultat(True, f"Postgame n'a aucune donnée {jeu} {mode} pour cette période.")
        return Resultat(True, f"Données Postgame ({jeu}, {mode or 'tous modes'}, {periode}) :\n{compacter(donnees)}",
                        donnees=donnees)


class DebriefPartie(Outil):
    nom = "debrief_partie"
    description = "Récupère le débrief détaillé d'une partie Postgame (par son identifiant, ou la dernière)."
    parametres = {"type": "object", "properties": {
        "jeu": {"type": "string", "enum": JEUX}, "id": {"type": "string", "description": "Vide = dernière partie."}},
        "required": ["jeu"]}
    hotes = ("127.0.0.1", "localhost")

    async def executer(self, ctx: Contexte, jeu: str, id: str = "") -> Resultat:  # noqa: A002
        client = ClientPostgame(ctx, self)
        try:
            if not id:
                parties = await client.appel("parties", jeu=jeu, limite=1)
                liste = parties.get("parties", parties) if isinstance(parties, dict) else parties
                if not liste:
                    return Resultat(True, f"Aucune partie {jeu} dans Postgame.")
                id = str(liste[0].get("id"))
            debrief = await client.appel("debrief", id)
        except Exception as e:  # noqa: BLE001
            return Resultat.echec(f"Débrief indisponible : {type(e).__name__} {e}")
        return Resultat(True, f"Débrief Postgame de la partie {id} :\n{compacter(debrief)}", donnees=debrief)


OUTILS = [StatistiquesJeu, DebriefPartie]
