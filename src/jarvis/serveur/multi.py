"""Socle multi-appareils (lot J12) : présence, notifications routées, outils distants, transferts.

- MULTI-02 : présence — dernier appareil utilisé (interaction, ou clavier/souris pour le PC).
- MULTI-05 : une notification va d'abord à l'appareil actif ; les autres ne la reçoivent que si
  elle n'a pas été lue après un délai (pas de doublon).
- MAC-05 / MULTI-04 : un appareil connecté déclare ses outils (pilotage du Mac, sonnerie du
  téléphone…) ; ils entrent dans le registre sous la forme `<appareil>_<outil>`, avec leur
  niveau de permission, et s'exécutent sur l'appareil via la connexion WebSocket.
- Transferts : un fichier du PC est mis à disposition par un lien à usage unique.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

log = logging.getLogger(__name__)
DELAI_RELAIS_S = 60
DELAI_OUTIL_DISTANT_S = 60
DUREE_LIEN_S = 600


@dataclass
class Connexion:
    appareil: dict
    ws: object  # WebSocket starlette
    outils: list[dict] = field(default_factory=list)


class OutilDistant(Outil):
    """Outil exécuté par un appareil connecté (Mac, téléphone)."""

    def __init__(self, gestionnaire: GestionnaireMulti, ident_appareil: str, nom_appareil: str, definition: dict):
        self.gestionnaire = gestionnaire
        self.ident_appareil = ident_appareil
        self.nom_distant = definition["nom"]
        prefixe = re.sub(r"[^a-z0-9]+", "_", nom_appareil.lower()).strip("_") or "appareil"
        self.nom = f"{prefixe}_{definition['nom']}"[:60]
        self.description = f"[{nom_appareil}] {definition.get('description', '')}"
        self.parametres = definition.get("parametres") or {"type": "object", "properties": {}}
        niveau = definition.get("niveau", "irreversible")
        self.niveau = {"lecture": Niveau.LECTURE, "reversible": Niveau.REVERSIBLE}.get(niveau, Niveau.IRREVERSIBLE)
        self.lit_contenu_externe = bool(definition.get("lit_contenu_externe"))

    async def executer(self, ctx: Contexte, **args) -> Resultat:
        return await self.gestionnaire.executer_distant(self.ident_appareil, self.nom_distant, args)


class GestionnaireMulti:
    def __init__(self, jarvis):
        self.jarvis = jarvis
        self.connexions: dict[str, list[Connexion]] = {}
        self._attentes: dict[str, asyncio.Future] = {}
        self._notifications: dict[str, dict] = {}  # id -> {lu, evenement}
        self._liens: dict[str, tuple[Path, float]] = {}
        jarvis.services["multi"] = self

    # --- Connexions et présence ---------------------------------------------------------------

    async def ouvrir(self, appareil: dict, ws) -> Connexion:
        c = Connexion(appareil, ws)
        self.connexions.setdefault(appareil["id"], []).append(c)
        self.jarvis.bus.publier("appareil", id=appareil["id"], nom=appareil.get("nom"), etat="connecte")
        return c

    def fermer(self, c: Connexion) -> None:
        liste = self.connexions.get(c.appareil["id"], [])
        if c in liste:
            liste.remove(c)
        if not liste:
            self.connexions.pop(c.appareil["id"], None)
            self._retirer_outils(c.appareil["id"])
            self.jarvis.bus.publier("appareil", id=c.appareil["id"], nom=c.appareil.get("nom"), etat="deconnecte")

    def appareil_actif(self) -> str:
        """MULTI-02 : PC si Mathieu y est (clavier/souris récents ou en jeu), sinon le dernier appareil utilisé."""
        from jarvis.outils import windows as win

        try:
            pc_actif = win.secondes_inactivite() < 120 or self.jarvis.etat_jeu.get("en_jeu")
        except Exception:  # noqa: BLE001
            pc_actif = True
        if pc_actif:
            return "pc"
        actif = self.jarvis.appareils.appareil_actif()
        return actif if actif and actif in self.connexions else "pc"

    async def envoyer(self, ident: str, message: dict) -> bool:
        envoye = False
        for c in list(self.connexions.get(ident, [])):
            try:
                await c.ws.send_text(json.dumps(message, ensure_ascii=False, default=str))
                envoye = True
            except Exception:  # noqa: BLE001
                self.fermer(c)
        return envoye

    async def diffuser(self, message: dict, sauf: set[str] | None = None) -> None:
        for ident in list(self.connexions):
            if not sauf or ident not in sauf:
                await self.envoyer(ident, message)

    # --- Notifications sans doublon (MULTI-05) ------------------------------------------------

    async def notifier(self, evenement: dict) -> str:
        ident = secrets.token_hex(4)
        evenement = {**evenement, "donnees": {**evenement.get("donnees", {}), "id_notification": ident}}
        self._notifications[ident] = {"lu": False, "evenement": evenement}
        actif = self.appareil_actif()
        if actif != "pc":
            await self.envoyer(actif, evenement)
        else:
            await self.envoyer("pc", evenement)
        asyncio.create_task(self._relayer(ident, actif))
        return ident

    async def _relayer(self, ident: str, deja: str) -> None:
        await asyncio.sleep(DELAI_RELAIS_S)
        n = self._notifications.get(ident)
        if n and not n["lu"]:
            await self.diffuser(n["evenement"], sauf={deja})

    def marquer_lu(self, ident: str) -> None:
        if ident in self._notifications:
            self._notifications[ident]["lu"] = True

    # --- Outils distants (MAC-05, MULTI-04) ---------------------------------------------------

    def enregistrer_outils(self, c: Connexion, definitions: list[dict]) -> list[str]:
        self._retirer_outils(c.appareil["id"])
        noms = []
        for d in definitions[:60]:
            if not isinstance(d, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", str(d.get("nom", ""))):
                continue
            outil = OutilDistant(self, c.appareil["id"], c.appareil.get("nom", "appareil"), d)
            if outil.nom in self.jarvis.registre:
                continue
            self.jarvis.registre.outils[outil.nom] = outil
            noms.append(outil.nom)
        c.outils = definitions
        log.info("Outils de %s : %s", c.appareil.get("nom"), ", ".join(noms))
        return noms

    def _retirer_outils(self, ident_appareil: str) -> None:
        for nom in [n for n, o in self.jarvis.registre.outils.items()
                    if isinstance(o, OutilDistant) and o.ident_appareil == ident_appareil]:
            del self.jarvis.registre.outils[nom]

    async def executer_distant(self, ident_appareil: str, outil: str, args: dict) -> Resultat:
        if ident_appareil not in self.connexions:
            return Resultat.echec("Cet appareil n'est pas connecté.")
        ident = secrets.token_hex(6)
        futur = asyncio.get_running_loop().create_future()
        self._attentes[ident] = futur
        await self.envoyer(ident_appareil, {"type": "executer", "donnees": {"id": ident, "outil": outil, "args": args}})
        try:
            r = await asyncio.wait_for(futur, DELAI_OUTIL_DISTANT_S)
        except TimeoutError:
            return Resultat.echec("L'appareil n'a pas répondu.")
        finally:
            self._attentes.pop(ident, None)
        return Resultat(bool(r.get("ok")), str(r.get("message", ""))[:6000],
                        contenu_externe=bool(r.get("contenu_externe")))

    def resultat_distant(self, donnees: dict) -> None:
        futur = self._attentes.get(str(donnees.get("id")))
        if futur and not futur.done():
            futur.set_result(donnees)

    # --- Transferts ---------------------------------------------------------------------------

    def lien_fichier(self, chemin: Path) -> str:
        jeton = secrets.token_urlsafe(24)
        self._liens[jeton] = (chemin, time.time() + DUREE_LIEN_S)
        return f"/api/fichiers/{jeton}"

    def fichier_pour_lien(self, jeton: str) -> Path | None:
        chemin, expire = self._liens.pop(jeton, (None, 0))  # usage unique
        return chemin if chemin and time.time() < expire and chemin.is_file() else None
