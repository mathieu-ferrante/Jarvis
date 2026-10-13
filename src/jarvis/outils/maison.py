"""OUT-MAI : maison connectée via Home Assistant, en local (API REST du réseau domestique).

Lumières, prises, volets, climat, médias : actions réversibles (annoncées). Serrures, alarme,
portes de garage et portails : sensibles, donc toujours confirmées (SEC-01).
Jeton longue durée dans le coffre : `python -m jarvis secrets definir home_assistant_jeton`.
"""

from __future__ import annotations

import difflib
import unicodedata
from urllib.parse import urlparse

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

DOMAINES_SENSIBLES = {"lock", "alarm_control_panel"}
CLASSES_SENSIBLES = {"garage", "gate", "door"}  # device_class des « cover » sensibles
DOMAINES_PILOTABLES = {"light", "switch", "fan", "cover", "climate", "media_player", "scene", "script", "input_boolean",
                       "vacuum", "humidifier", "lock", "alarm_control_panel"}


def _norm(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in texte if not unicodedata.combining(c))


class HomeAssistant:
    def __init__(self, ctx: Contexte, outil: Outil):
        self.ctx = ctx
        self.base = ctx.config.integrations.home_assistant_url.rstrip("/")
        if not self.base:
            raise RuntimeError("Home Assistant non configuré ([integrations] home_assistant_url)")
        self.hote = urlparse(self.base).hostname or ""
        jeton = ctx.coffre.lire("home_assistant_jeton") if ctx.coffre else None
        if not jeton:
            raise RuntimeError("jeton absent : python -m jarvis secrets definir home_assistant_jeton")
        self.entetes = {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"}

    async def etats(self) -> list[dict]:
        r = await self.ctx.http("GET", f"{self.base}/api/states", hotes=(self.hote,), headers=self.entetes)
        r.raise_for_status()
        autorisees = set(self.ctx.config.integrations.home_assistant_entites or [])
        return [e for e in r.json() if not autorisees or e["entity_id"] in autorisees]

    async def service(self, domaine: str, service: str, donnees: dict) -> list:
        r = await self.ctx.http("POST", f"{self.base}/api/services/{domaine}/{service}", hotes=(self.hote,),
                                headers=self.entetes, json=donnees)
        r.raise_for_status()
        return r.json()


def nom_entite(e: dict) -> str:
    return e.get("attributes", {}).get("friendly_name") or e["entity_id"]


def trouver_entite(etats: list[dict], recherche: str) -> dict | None:
    if any(e["entity_id"] == recherche for e in etats):
        return next(e for e in etats if e["entity_id"] == recherche)
    pilotables = [e for e in etats if e["entity_id"].split(".")[0] in DOMAINES_PILOTABLES]
    noms = {_norm(nom_entite(e)): e for e in pilotables}
    r = _norm(recherche)
    contient = [n for n in noms if r in n or all(m in n for m in r.split())]
    if contient:
        return noms[min(contient, key=len)]
    proche = difflib.get_close_matches(r, list(noms), n=1, cutoff=0.6)
    return noms[proche[0]] if proche else None


def est_sensible(e: dict) -> bool:
    domaine = e["entity_id"].split(".")[0]
    return domaine in DOMAINES_SENSIBLES or (domaine == "cover" and
                                             e.get("attributes", {}).get("device_class") in CLASSES_SENSIBLES)


def service_pour(e: dict, action: str, valeur: float | None) -> tuple[str, str, dict]:
    domaine = e["entity_id"].split(".")[0]
    donnees: dict = {"entity_id": e["entity_id"]}
    if domaine == "cover":
        service = {"allumer": "open_cover", "ouvrir": "open_cover", "eteindre": "close_cover", "fermer": "close_cover",
                   "regler": "set_cover_position"}.get(action, "toggle")
        if service == "set_cover_position":
            donnees["position"] = int(valeur or 0)
    elif domaine == "lock":
        service = {"ouvrir": "unlock", "eteindre": "lock", "fermer": "lock", "allumer": "unlock"}.get(action, "lock")
    elif domaine == "alarm_control_panel":
        service = "alarm_arm_away" if action in ("allumer", "fermer") else "alarm_disarm"
    elif domaine == "climate" and action == "regler":
        service, donnees["temperature"] = "set_temperature", float(valeur or 20)
    elif domaine in ("scene", "script"):
        service = "turn_on"
    elif domaine == "media_player" and action == "regler":
        service, donnees["volume_level"] = "volume_set", max(0.0, min(1.0, (valeur or 0) / 100))
    else:
        service = {"allumer": "turn_on", "ouvrir": "turn_on", "eteindre": "turn_off", "fermer": "turn_off",
                   "basculer": "toggle", "regler": "turn_on"}.get(action, "toggle")
        if domaine == "light" and action == "regler" and valeur is not None:
            donnees["brightness_pct"] = int(valeur)
    return domaine, service, donnees


class EtatMaison(Outil):
    nom = "etat_maison"
    description = "Donne l'état de la maison connectée (lumières, capteurs, températures…), ou d'un appareil précis."
    parametres = {"type": "object", "properties": {"appareil": {"type": "string", "description": "Facultatif."}}}

    async def executer(self, ctx: Contexte, appareil: str = "") -> Resultat:
        ha = HomeAssistant(ctx, self)
        etats = await ha.etats()
        if appareil:
            mots = _norm(appareil).split()
            tous_les_mots = [x for x in etats if all(m in _norm(nom_entite(x)) for m in mots)]
            e = (min(tous_les_mots, key=lambda x: len(nom_entite(x))) if tous_les_mots
                 else trouver_entite(etats, appareil))
            if not e:
                return Resultat.echec(f"Aucun appareil « {appareil} ».")
            unite = e.get("attributes", {}).get("unit_of_measurement", "")
            return Resultat(True, f"{nom_entite(e)} : {e['state']}{(' ' + unite) if unite else ''}.")
        interessants = [e for e in etats if e["entity_id"].split(".")[0] in DOMAINES_PILOTABLES | {"sensor", "binary_sensor"}]
        lignes = [f"{nom_entite(e)} : {e['state']}{(' ' + e['attributes'].get('unit_of_measurement', '')) if e.get('attributes', {}).get('unit_of_measurement') else ''}"
                  for e in interessants[:60]]
        return Resultat(True, "\n".join(lignes) or "Aucun appareil.")


class _Commande(Outil):
    parametres = {"type": "object", "properties": {
        "appareil": {"type": "string", "description": "Nom de l'appareil (ex. « lumière du salon »)."},
        "action": {"type": "string", "enum": ["allumer", "eteindre", "basculer", "ouvrir", "fermer", "regler"]},
        "valeur": {"type": "number", "description": "Pour régler : luminosité %, température °C, position %."}},
        "required": ["appareil", "action"]}
    sensible = False

    def decrire(self, args):
        valeur = f" à {args['valeur']}" if args.get("valeur") is not None else ""
        return f"{args.get('action')} {args.get('appareil')}{valeur}"

    async def executer(self, ctx: Contexte, appareil: str, action: str, valeur: float | None = None) -> Resultat:
        ha = HomeAssistant(ctx, self)
        e = trouver_entite(await ha.etats(), appareil)
        if e is None:
            return Resultat.echec(f"Aucun appareil pilotable « {appareil} ».")
        if est_sensible(e) != self.sensible:
            autre = "commander_securite_maison" if est_sensible(e) else "commander_maison"
            return Resultat.echec(f"{nom_entite(e)} se commande avec l'outil {autre}.")
        domaine, service, donnees = service_pour(e, action, valeur)
        await ha.service(domaine, service, donnees)
        return Resultat(True, f"{nom_entite(e)} : {service.replace('_', ' ')}.", donnees={"entite": e["entity_id"],
                                                                                         "service": service})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        attendu = {"turn_on": "on", "turn_off": "off", "open_cover": "open", "close_cover": "closed",
                   "lock": "locked", "unlock": "unlocked"}.get(resultat.donnees["service"])
        if not attendu:
            return None
        import asyncio

        await asyncio.sleep(1.5)
        etats = await HomeAssistant(ctx, self).etats()
        e = next((x for x in etats if x["entity_id"] == resultat.donnees["entite"]), None)
        return None if e is None else e["state"] in (attendu, "opening" if attendu == "open" else attendu)


class CommanderMaison(_Commande):
    nom = "commander_maison"
    description = "Commande un appareil de la maison : lumière, prise, volet, chauffage, enceinte, scène."
    niveau = Niveau.REVERSIBLE


class CommanderSecuriteMaison(_Commande):
    nom = "commander_securite_maison"
    description = "Commande un équipement de sécurité (serrure, alarme, porte de garage, portail). Toujours confirmé."
    niveau = Niveau.IRREVERSIBLE
    sensible = True


OUTILS = [EtatMaison, CommanderMaison, CommanderSecuriteMaison]
