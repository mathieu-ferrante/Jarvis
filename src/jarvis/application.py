"""Assemblage de Jarvis : tous les composants, leur démarrage et leurs interactions.

Démarrage rapide (PERF-09) : le serveur web et la voix démarrent pendant que le modèle se
charge en tâche de fond ; les composants lourds sont importés à la demande.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from jarvis import chemins
from jarvis import config as module_config
from jarvis.agent.orchestrateur import Orchestrateur
from jarvis.agent.taches import GestionnaireTaches
from jarvis.evenements import Bus, Evenement
from jarvis.llm.client import ClientLLM
from jarvis.llm.serveur import Lancement, ServeurModele
from jarvis.memoire.stockage import Memoire
from jarvis.memoire.vecteurs import PlongeurAvecRepli, PlongeurLocal
from jarvis.outils.registre import Registre
from jarvis.rappels import ServiceRappels
from jarvis.securite import permissions
from jarvis.securite.journal import Journal
from jarvis.securite.reseau import GARDE
from jarvis.serveur.appareils import Appareils

log = logging.getLogger(__name__)


@dataclass
class Metriques:
    """Tableau de bord (J11) : derniers échanges et état des ressources."""

    echanges: list[dict] = field(default_factory=list)
    demarrage_s: float | None = None
    pret: bool = False

    def ajouter(self, **valeurs) -> None:
        self.echanges.append({"horodatage": time.time(), **valeurs})
        del self.echanges[:-200]


class Jarvis:
    def __init__(self, config: module_config.Config | None = None, avec_voix: bool = True,
                 avec_modeles: bool = True):
        self.debut = time.monotonic()
        self.config = config or module_config.charger()
        self.avec_voix, self.avec_modeles = avec_voix, avec_modeles
        self.bus = Bus()
        self.metriques = Metriques()
        self.journal = Journal()
        try:
            from jarvis.securite.secrets import Coffre

            self.coffre = Coffre()
            self.coffre.noms()
        except OSError:
            log.warning("Coffre indisponible (DPAPI) : intégrations à secrets désactivées")
            self.coffre = None
        c = self.config.llm
        self.serveur_llm = ServeurModele()
        self.serveur_embeddings = ServeurModele(chemins.dossier_donnees() / "journaux" / "llama-embeddings.log")
        url = c.url_externe or f"http://127.0.0.1:{c.port}"
        self.llm = ClientLLM(url, temperature=c.temperature)
        self.llm_rapide = self.llm
        self.memoire = Memoire(plongeur=PlongeurAvecRepli(PlongeurLocal(f"http://127.0.0.1:{c.port_embeddings}")))
        self.rappels = ServiceRappels(bus=self.bus)
        from jarvis.contexte_rappels import RappelsContexte

        self.rappels_contexte = RappelsContexte(bus=self.bus)
        self.bus.abonner(self.rappels_contexte.sur_evenement)
        self.appareils = Appareils()
        self.registre = Registre().charger_tout()
        for erreur in self.registre.erreurs:
            log.warning("Outils non chargés : %s", erreur)
        self.confirmateur = permissions.ConfirmateurFile(self._publier_confirmation, delai_s=90)
        self.services: dict = {"rappels": self.rappels, "rappels_contexte": self.rappels_contexte,
                               "bus": self.bus, "appareils": self.appareils,
                               "application": self, "llm": self.llm}
        self.etat_jeu = {"en_jeu": False, "jeu": None}
        self.orchestrateur = Orchestrateur(
            self.llm, self.registre, self.journal, self.confirmateur, self.bus, llm_rapide=self.llm_rapide,
            config=self.config, memoire=self.memoire, coffre=self.coffre, services=self.services,
            en_jeu=lambda: self.etat_jeu["en_jeu"])
        self.services["taches"] = GestionnaireTaches(self.orchestrateur)
        from jarvis.agent.contexte import CONSIGNES
        from jarvis.agent.personnalisation import bloc_consignes

        self.orchestrateur.consignes = CONSIGNES + bloc_consignes(self.journal.dernieres(500))
        from jarvis.serveur.multi import GestionnaireMulti

        self.multi = GestionnaireMulti(self)
        self.boucle = None
        self._taches: list[asyncio.Task] = []
        self.bus.abonner(self._sur_evenement)

    # --- Confirmations (SEC-01) -------------------------------------------------------------

    async def _publier_confirmation(self, ident: int, demande: permissions.Demande) -> None:
        self.bus.publier("confirmation", id=ident, question=demande.question(), outil=demande.outil,
                         arguments=demande.arguments, niveau=demande.niveau.nom_fr,
                         suite_contenu_externe=demande.suite_contenu_externe, appareil=demande.appareil)
        if self.boucle is not None and self.boucle.etat in ("reflexion", "parole"):
            asyncio.create_task(self._confirmer_a_la_voix(ident, demande.question()))

    async def _confirmer_a_la_voix(self, ident: int, question: str) -> None:
        reponse = await self.boucle.demander_confirmation(question)
        if reponse is not None:
            self.confirmateur.repondre(ident, reponse)

    # --- Évènements -------------------------------------------------------------------------

    def _sur_evenement(self, evt: Evenement) -> None:
        if evt.type == "notification" and self.boucle is not None:
            urgent = evt.donnees.get("urgent") and evt.donnees.get("categorie") in self.config.jeu.alertes_autorisees
            self.boucle.annoncer(f"{evt.donnees.get('titre')} : {evt.donnees.get('texte')}",
                                 urgent=bool(urgent) or not self.etat_jeu["en_jeu"])
        if evt.type == "arret" and self.boucle is not None:
            self.boucle.arreter_tout()

    # --- Démarrage --------------------------------------------------------------------------

    async def demarrer_modeles(self) -> None:
        c = self.config.llm
        if c.url_externe:
            self.metriques.pret = True
            return
        try:
            await self.serveur_llm.demarrer(Lancement(c.principal, c.backend, c.port, c.contexte,
                                                      speculatif=c.speculatif, brouillon=c.brouillon,
                                                      cache_kv=c.cache_kv))
            await self.prechauffer()
            self.metriques.pret = True
            self.metriques.demarrage_s = round(time.monotonic() - self.debut, 1)
            self.bus.publier("pret", demarrage_s=self.metriques.demarrage_s)
            log.info("Jarvis prêt en %.1f s", self.metriques.demarrage_s)
        except Exception as e:  # noqa: BLE001
            log.exception("Modèle principal non démarré")
            self.bus.notifier("Modèle indisponible", f"Le modèle de langage n'a pas démarré : {e}", urgent=True)
        try:
            await self.serveur_embeddings.demarrer(Lancement("embeddings", "cpu", c.port_embeddings))
        except Exception:  # noqa: BLE001 — repli sur le hachage
            log.warning("Serveur d'embeddings non démarré : recherche mémoire en mode dégradé")

    async def prechauffer(self) -> None:
        """Remplit le cache du contexte fixe (consignes + outils) : la 1re vraie requête est rapide (PERF-06)."""
        messages = [{"role": "system", "content": self.orchestrateur.consignes}, {"role": "user", "content": "Bonjour."}]
        try:
            await self.llm.discuter(messages, self.orchestrateur.schemas_actifs(), max_tokens=1)
        except Exception:  # noqa: BLE001
            log.warning("Préchauffage impossible")

    def demarrer_voix(self) -> None:
        from jarvis.voix import moteurs
        from jarvis.voix.audio_es import Micro, SortieAudio
        from jarvis.voix.boucle import BoucleVocale, ParametresBoucle

        v = self.config.voix
        stt = moteurs.creer_transcripteur(v)
        self.boucle = BoucleVocale(
            entree=Micro(v.micro or None), sortie=SortieAudio(v.sortie or None),
            reveil=moteurs.DetecteurReveil(v.seuil_reveil, v.seuil_reveil_bas, stt),
            vad=moteurs.DetecteurParole(), stt=stt, tts=moteurs.Synthese(v.tts), cerveau=self.orchestrateur,
            parametres=ParametresBoucle(fin_de_parole_ms=v.fin_de_parole_ms, duree_max_phrase_s=v.duree_max_phrase_s,
                                        ecoute_continue_s=v.ecoute_continue_s, interruption=v.interruption,
                                        anticipation_ms=v.anticipation_ms),
            sur_evenement=self._evenement_voix, silencieux=lambda: self.etat_jeu["en_jeu"])
        if v.annulation_echo:
            from jarvis.voix.aec import AnnuleurEcho, FileReference

            self.boucle.sortie.reference = FileReference()
            self.boucle.aec = AnnuleurEcho()
        if self.coffre is not None:
            from jarvis.voix.locuteur import VerificateurLocuteur

            verificateur = VerificateurLocuteur(self.coffre)
            if verificateur.actif:  # seulement après l'enrôlement de la voix de Mathieu
                self.boucle.verificateur = verificateur

    def _evenement_voix(self, type_: str, donnees: dict) -> None:
        self.bus.publier(f"voix_{type_}", **donnees)
        if type_ == "latence":
            m = self.boucle.mesures[-1]
            self.metriques.ajouter(
                canal="voix", texte=m.texte, latence_ms=m.latence_ms,
                transcription_ms=round(1000 * (m.transcription - m.fin_parole)),
                premier_texte_ms=round(1000 * (m.premier_texte - m.transcription)) if m.premier_texte else None,
                voix_ms=round(1000 * (m.premier_son - m.premier_texte)) if m.premier_texte else None)

    async def executer(self, avec_api: bool = True, avec_bureau: bool = False) -> None:
        GARDE.installer()  # SEC-04 : à partir d'ici, aucune sortie non déclarée
        self._taches.append(asyncio.create_task(self.rappels.boucle()))
        repris = self.services["taches"].reprendre()  # IA-02 : tâches interrompues par un arrêt
        if repris:
            log.info("Tâches de fond reprises : %s", repris)

        async def position():
            from jarvis.outils.base import Contexte
            from jarvis.outils.rappels import position_du_telephone

            resultat = await position_du_telephone(Contexte(config=self.config, services=self.services))
            # Consultation sensible : consignée même quand elle est automatique (SEC-03)
            self.journal.consigner(outil="position_telephone", arguments={}, niveau="lecture", decision="libre",
                                   demande="vérification des rappels de lieu", origine="initiative",
                                   ok=resultat is not None, resultat="position obtenue" if resultat else "indisponible")
            return resultat

        self._taches.append(asyncio.create_task(self.rappels_contexte.boucle_position(position)))
        if self.avec_modeles:
            self._taches.append(asyncio.create_task(self.demarrer_modeles()))
        from jarvis.initiative import Initiative
        from jarvis.jeu import DetecteurJeu

        self.detecteur_jeu = DetecteurJeu(self)
        self._taches.append(asyncio.create_task(self.detecteur_jeu.boucle()))
        self.initiative = Initiative(self)
        self._taches.append(asyncio.create_task(self.initiative.boucle()))
        if self.avec_voix:
            try:
                await asyncio.to_thread(self.demarrer_voix)
                self._taches.append(asyncio.create_task(self.boucle.executer()))
            except Exception as e:  # noqa: BLE001 — pas de micro : Jarvis reste utilisable au texte
                log.exception("Voix indisponible")
                self.bus.notifier("Voix indisponible", str(e))
        if avec_api:
            from jarvis.serveur.api import servir

            self._taches.append(asyncio.create_task(servir(self)))
        await asyncio.gather(*self._taches)

    async def arreter(self) -> None:
        for t in self._taches:
            t.cancel()
        if self.boucle:
            self.boucle.fermer()
        await self.serveur_llm.arreter()
        await self.serveur_embeddings.arreter()
        await self.llm.fermer()
