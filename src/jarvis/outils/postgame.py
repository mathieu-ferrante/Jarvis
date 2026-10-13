"""OUT-JEU : le coach de jeux Postgame, par son API locale (http://127.0.0.1:8765 par défaut).

Points d'API utilisés (Postgame, `src/postgame/api.py`) : `/api/parties?jeu=&limite=`,
`/api/parties/{id}` (fiche + mesures + preuves), `/api/comptes` (classements), `/api/tft/stats`.

RÈGLE ABSOLUE : Postgame fait rédiger ses débriefs par une IA dans le cloud (Gemini). Jarvis
n'appelle donc JAMAIS `/api/parties/{id}/debrief`, qui déclencherait cette rédaction : il lit
les mesures locales et c'est son propre modèle, local, qui rédige le débrief.
"""

from __future__ import annotations

import json
import statistics
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlparse

from jarvis.outils.base import Contexte, Outil, Resultat

JEUX = ["cs2", "lol", "tft", "geometry_dash"]
CHEMINS_INTERDITS = ("/debrief", "/debriefs")  # rédaction par IA distante côté Postgame
ECART_SESSION = timedelta(hours=3)
SYNONYMES_MODES = {"dm": "deathmatch", "match a mort": "deathmatch", "classee": "premier", "ranked": "classe"}


def _norm(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in texte if not unicodedata.combining(c)).strip()


class ClientPostgame:
    def __init__(self, ctx: Contexte):
        self.ctx = ctx
        self.base = ctx.config.integrations.postgame_url.rstrip("/")
        self.hote = urlparse(self.base).hostname or "127.0.0.1"

    async def get(self, chemin: str, **params):
        if any(interdit in chemin for interdit in CHEMINS_INTERDITS):
            raise PermissionError("débrief Postgame rédigé par une IA distante : interdit à Jarvis (SEC-04)")
        r = await self.ctx.http("GET", self.base + chemin, hotes=(self.hote,),
                                params={k: v for k, v in params.items() if v not in (None, "")})
        if r.status_code == 404:
            raise LookupError(chemin)
        r.raise_for_status()
        return r.json()

    async def parties(self, jeu: str, limite: int = 50) -> list[dict]:
        donnees = await self.get("/api/parties", jeu=jeu, limite=limite)
        return donnees.get("parties", []) if isinstance(donnees, dict) else list(donnees)

    async def fiche(self, ident) -> dict:
        return await self.get(f"/api/parties/{ident}")


def _date(p: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(p.get("date_partie", "")).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def filtrer_mode(parties: list[dict], mode: str) -> list[dict]:
    if not mode:
        return parties
    m = SYNONYMES_MODES.get(_norm(mode), _norm(mode))
    return [p for p in parties if m in _norm(str(p.get("mode", "")))]


def derniere_session(parties: list[dict]) -> list[dict]:
    """Parties consécutives (moins de 3 h d'écart) les plus récentes. `parties` : plus récentes d'abord."""
    session: list[dict] = []
    for p in parties:
        if not session:
            session.append(p)
            continue
        precedente, actuelle = _date(session[-1]), _date(p)
        if precedente and actuelle and precedente - actuelle <= ECART_SESSION:
            session.append(p)
        else:
            break
    return session


def mesures_numeriques(fiche: dict) -> dict[str, float]:
    """{nom: valeur} pour les mesures chiffrées d'une fiche (format souple)."""
    sortie: dict[str, float] = {}
    for m in fiche.get("mesures", []) or []:
        if isinstance(m, dict):
            nom = m.get("nom") or m.get("mesure") or m.get("cle")
            valeur = m.get("valeur", m.get("value"))
            if nom and isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
                sortie[str(nom)] = float(valeur)
    return sortie


def tendance(fiches: list[dict]) -> dict[str, dict]:
    """Compare la moyenne des parties récentes à celle des plus anciennes, mesure par mesure."""
    if len(fiches) < 4:
        return {}
    moitie = len(fiches) // 2
    recentes, anciennes = fiches[:moitie], fiches[moitie:]
    noms = set().union(*(mesures_numeriques(f) for f in fiches))
    resultat = {}
    for nom in sorted(noms):
        r = [mesures_numeriques(f)[nom] for f in recentes if nom in mesures_numeriques(f)]
        a = [mesures_numeriques(f)[nom] for f in anciennes if nom in mesures_numeriques(f)]
        if r and a:
            resultat[nom] = {"recent": round(statistics.mean(r), 2), "avant": round(statistics.mean(a), 2)}
    return resultat


def compacter(donnees, limite: int = 6000) -> str:
    texte = json.dumps(donnees, ensure_ascii=False, default=str)
    return texte if len(texte) <= limite else texte[:limite] + " … (tronqué)"


class StatistiquesJeu(Outil):
    nom = "statistiques_jeu"
    description = ("Interroge le coach de jeux Postgame : dernière session, dernières parties ou progression, pour "
                   "CS2, LoL, TFT ou Geometry Dash, avec les vraies mesures. Réponds ensuite avec ces chiffres, "
                   "sans en inventer.")
    parametres = {"type": "object", "properties": {
        "jeu": {"type": "string", "enum": JEUX},
        "mode": {"type": "string", "description": "Facultatif : deathmatch, premier, aram, classé…"},
        "vue": {"type": "string", "enum": ["derniere_session", "dernieres_parties", "progression", "classements"]}},
        "required": ["jeu"]}
    hotes = ("127.0.0.1", "localhost")

    async def executer(self, ctx: Contexte, jeu: str, mode: str = "", vue: str = "derniere_session") -> Resultat:
        client = ClientPostgame(ctx)
        try:
            if vue == "classements":
                return Resultat(True, f"Classements (Postgame) : {compacter(await client.get('/api/comptes'))}")
            if jeu == "tft" and vue == "progression":
                return Resultat(True, f"TFT (Postgame) : {compacter(await client.get('/api/tft/stats'))}")
            parties = filtrer_mode(await client.parties(jeu, 100 if vue == "progression" else 40), mode)
            if not parties:
                return Resultat(True, f"Postgame n'a aucune partie de {jeu}{' en ' + mode if mode else ''}.")
            if vue == "derniere_session":
                choisies = derniere_session(parties)[:8]
            elif vue == "dernieres_parties":
                choisies = parties[:10]
            else:
                choisies = parties[:12]
            fiches = [await client.fiche(p["id"]) for p in choisies]
        except LookupError:
            return Resultat.echec("Postgame répond, mais pas à ce chemin : son API a peut-être changé.")
        except PermissionError as e:
            return Resultat.echec(str(e))
        except Exception as e:  # noqa: BLE001
            return Resultat.echec(f"Postgame est injoignable ({type(e).__name__}) : est-il lancé ?")
        resume = [{**{k: p.get(k) for k in ("date_partie", "mode", "carte", "resultat", "score_joueur",
                                             "score_adverse", "duree_s")},
                   "mesures": mesures_numeriques(f)} for p, f in zip(choisies, fiches, strict=True)]
        donnees: dict = {"jeu": jeu, "mode": mode or "tous", "vue": vue, "parties": resume}
        if vue == "progression":
            donnees["tendance"] = tendance(fiches)
        return Resultat(True, f"Données Postgame : {compacter(donnees)}", donnees=donnees)


class DebriefPartie(Outil):
    nom = "debrief_partie"
    description = ("Récupère la fiche détaillée d'une partie Postgame (mesures, moments clés) pour en faire le "
                   "débrief toi-même : 3 priorités, points forts, avec les vrais chiffres.")
    parametres = {"type": "object", "properties": {
        "jeu": {"type": "string", "enum": JEUX}, "id": {"type": "string", "description": "Vide = dernière partie."}},
        "required": ["jeu"]}
    hotes = ("127.0.0.1", "localhost")

    async def executer(self, ctx: Contexte, jeu: str, id: str = "") -> Resultat:  # noqa: A002
        client = ClientPostgame(ctx)
        try:
            if not id:
                parties = await client.parties(jeu, 1)
                if not parties:
                    return Resultat(True, f"Aucune partie {jeu} dans Postgame.")
                id = str(parties[0]["id"])
            fiche = await client.fiche(id)  # données locales seulement, jamais /debrief
        except Exception as e:  # noqa: BLE001
            return Resultat.echec(f"Fiche Postgame indisponible : {type(e).__name__} {e}")
        fiche = {**fiche, "preuves": (fiche.get("preuves") or [])[:12]}
        return Resultat(True, "Fiche Postgame (rédige le débrief à partir de ces mesures) : " + compacter(fiche, 8000),
                        donnees=fiche)


OUTILS = [StatistiquesJeu, DebriefPartie]


class CoachEnDirect(Outil):
    nom = "coach_en_direct"
    description = ("Pendant une partie, SEULEMENT si Mathieu le demande (« un conseil ? ») : lit l'état en direct "
                   "fourni par Postgame (CS2 : GSI ; LoL : API locale du client) pour donner UN conseil bref et concret.")
    parametres = {"type": "object", "properties": {"jeu": {"type": "string", "enum": ["cs2", "lol"]}},
                  "required": ["jeu"]}
    hotes = ("127.0.0.1", "localhost")

    async def executer(self, ctx: Contexte, jeu: str) -> Resultat:
        try:
            etat = await ClientPostgame(ctx).get(f"/api/{jeu}/live")
        except Exception as e:  # noqa: BLE001
            return Resultat.echec(f"État en direct indisponible ({type(e).__name__}) : Postgame est-il lancé ?")
        if not etat or (isinstance(etat, dict) and not any(etat.values())):
            return Resultat(True, "Aucune partie en cours détectée par Postgame.")
        return Resultat(True, "État en direct (donne UN conseil, une phrase, sans chiffre inventé) : "
                              + compacter(etat, 3000), donnees=etat)


OUTILS.append(CoachEnDirect)
