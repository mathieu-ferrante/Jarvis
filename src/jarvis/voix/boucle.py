"""Boucle vocale (lot J1).

États :
- `veille`     : seul le mot de réveil est écouté (VOX-01) ;
- `ecoute`     : la phrase est enregistrée jusqu'à la fin de parole (silence) ;
- `reflexion`  : transcription puis réponse du cerveau, diffusée phrase par phrase (VOX-03) ;
- `parole`     : Jarvis parle ; « Jarvis » (ou toute parole en mode casque) l'interrompt (VOX-04) ;
- `suite`      : après une réponse, quelques secondes d'écoute sans mot de réveil (VOX-05).

Le cerveau est tout objet qui expose `repondre(texte, canal) -> AsyncIterator[str]`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from jarvis.voix.audio_es import TAUX, TRAME, EntreeAudio, SortieAudio
from jarvis.voix.phrases import DecoupeurPhrases

log = logging.getLogger(__name__)
DUREE_TRAME_MS = 1000 * TRAME / TAUX


class Cerveau(Protocol):
    def repondre(self, texte: str, canal: str = "voix") -> AsyncIterator[str]: ...


@dataclass
class Mesure:
    """Chronologie d'un échange, pour vérifier NF-01 sur le PC de jeu."""

    fin_parole: float = 0.0
    transcription: float = 0.0
    premier_texte: float = 0.0
    premier_son: float = 0.0
    texte: str = ""

    @property
    def latence_ms(self) -> float | None:
        if self.premier_son and self.fin_parole:
            return round(1000 * (self.premier_son - self.fin_parole))
        return None


@dataclass
class ParametresBoucle:
    fin_de_parole_ms: int = 400
    duree_max_phrase_s: float = 15.0
    attente_debut_s: float = 5.0  # après le réveil, délai pour commencer à parler
    ecoute_continue_s: float = 6.0
    interruption: str = "reveil"  # "reveil" ou "vad"
    seuil_parole: float = 0.5
    preambule_ms: int = 300  # audio gardé avant le début de parole détecté


_PREFIXE_REVEIL = re.compile(r"^\s*(h?[ée]+y?\s*,?\s*)?(dj?|j)a+r+v+i+\w*\s*[,.!?]?\s*", re.I)


def retirer_mot_reveil(texte: str) -> str:
    return _PREFIXE_REVEIL.sub("", texte).strip()


@dataclass
class BoucleVocale:
    entree: EntreeAudio
    sortie: SortieAudio
    reveil: object
    vad: object
    stt: object
    tts: object
    cerveau: Cerveau
    parametres: ParametresBoucle = field(default_factory=ParametresBoucle)
    sur_evenement: Callable[[str, dict], None] | None = None
    silencieux: Callable[[], bool] = lambda: False  # VOX-07 : en jeu, pas d'annonce spontanée

    def __post_init__(self):
        self.etat = "veille"
        self._tampon: list[np.ndarray] = []
        self._preambule: list[np.ndarray] = []
        self._parole_commencee = False
        self._silence_ms = 0.0
        self._debut_etat = time.monotonic()
        self._tache: asyncio.Task | None = None
        self._interruption_compte = 0
        self.mesures: list[Mesure] = []
        self._annonces: asyncio.Queue[str] = asyncio.Queue()
        self._arret = asyncio.Event()
        self._confirmation: asyncio.Future | None = None

    # --- Évènements -------------------------------------------------------------------------

    def _emettre(self, type_: str, **donnees) -> None:
        if self.sur_evenement:
            try:
                self.sur_evenement(type_, donnees)
            except Exception:  # noqa: BLE001 — l'interface ne doit pas casser la boucle
                log.exception("Erreur dans le gestionnaire d'évènements")

    def _changer_etat(self, etat: str) -> None:
        if etat != self.etat:
            log.debug("État : %s → %s", self.etat, etat)
            self.etat = etat
            self._debut_etat = time.monotonic()
            self._emettre("etat", etat=etat)

    # --- Commandes externes -----------------------------------------------------------------

    def declencher(self) -> None:
        """Appuyer pour parler / raccourci clavier : écoute immédiate sans mot de réveil."""
        self._interrompre()
        self._commencer_ecoute()

    def arreter_tout(self) -> None:
        """Bouton d'arrêt (SEC-07) : coupe la parole et la réponse en cours."""
        self._interrompre()
        self._changer_etat("veille")
        self.reveil.reinitialiser()
        self._emettre("arret")

    def annoncer(self, texte: str, urgent: bool = False) -> bool:
        """Annonce spontanée (rappel, fin de tâche). En jeu, seulement si `urgent` (VOX-07)."""
        if self.silencieux() and not urgent:
            self._emettre("annonce_retenue", texte=texte)
            return False
        self._annonces.put_nowait(texte)
        return True

    def fermer(self) -> None:
        self._arret.set()
        self._interrompre()

    # --- Boucle principale ------------------------------------------------------------------

    async def executer(self) -> None:
        annonces = asyncio.create_task(self._traiter_annonces())
        try:
            async for trame in self.entree.trames():
                if self._arret.is_set():
                    break
                self._traiter_trame(trame)
                await asyncio.sleep(0)
            if self._tache:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._tache
        finally:
            annonces.cancel()

    def _traiter_trame(self, trame: np.ndarray) -> None:
        p = self.parametres
        if self.etat == "veille":
            if self.reveil.traiter(trame):
                self._emettre("reveil")
                self._commencer_ecoute()
        elif self.etat in ("ecoute", "suite", "confirmation"):
            self._ecouter(trame)
        elif self.etat in ("reflexion", "parole"):
            if self._detecter_interruption(trame):
                log.info("Interruption")
                self._emettre("interruption")
                self._interrompre()
                self._commencer_ecoute()
        if self.etat == "suite" and not self._parole_commencee \
                and time.monotonic() - self._debut_etat > p.ecoute_continue_s:
            self._changer_etat("veille")
            self.reveil.reinitialiser()

    def _commencer_ecoute(self, etat: str = "ecoute") -> None:
        self._tampon = []
        self._parole_commencee = False
        self._silence_ms = 0.0
        self.vad.reinitialiser()
        # Le détecteur de réveil garde ~2 s d'audio en mémoire : sans remise à zéro, le « Jarvis »
        # qui vient d'être détecté le redéclencherait pendant la réflexion (fausse interruption).
        self.reveil.reinitialiser()
        self._changer_etat(etat)

    def _ecouter(self, trame: np.ndarray) -> None:
        p = self.parametres
        parole = self.vad.probabilite(trame) >= p.seuil_parole
        if not self._parole_commencee:
            self._preambule.append(trame)
            del self._preambule[:-max(1, int(p.preambule_ms / DUREE_TRAME_MS))]
            if parole:
                self._parole_commencee = True
                self._tampon = list(self._preambule)
                self._emettre("parole")
            elif self.etat == "ecoute" and time.monotonic() - self._debut_etat > p.attente_debut_s:
                self._changer_etat("veille")
                self.reveil.reinitialiser()
            return
        self._tampon.append(trame)
        self._silence_ms = 0.0 if parole else self._silence_ms + DUREE_TRAME_MS
        trop_long = len(self._tampon) * DUREE_TRAME_MS > p.duree_max_phrase_s * 1000
        if self._silence_ms >= p.fin_de_parole_ms or trop_long:
            son = np.concatenate(self._tampon)
            if self.etat == "confirmation":
                self._changer_etat("reflexion")
                self._tache_confirmation = asyncio.create_task(self._transcrire_confirmation(son))
                return
            # NF-01 se mesure depuis la vraie fin de parole, silence d'attente compris
            mesure = Mesure(fin_parole=time.monotonic() - self._silence_ms / 1000)
            self._changer_etat("reflexion")
            self._tache = asyncio.create_task(self._repondre(son, mesure))

    def _detecter_interruption(self, trame: np.ndarray) -> bool:
        if self.parametres.interruption == "vad":
            parole = self.vad.probabilite(trame) >= 0.6
            self._interruption_compte = self._interruption_compte + 1 if parole else 0
            return self._interruption_compte >= 3  # 240 ms de parole continue
        return bool(self.reveil.traiter(trame))

    def _interrompre(self) -> None:
        self.sortie.couper()
        if self._tache and not self._tache.done():
            self._tache.cancel()
        self._tache = None
        self._interruption_compte = 0

    # --- Confirmation à la voix (SEC-01) ----------------------------------------------------

    async def demander_confirmation(self, question: str, delai_s: float = 12.0) -> bool | None:
        """Pose la question, écoute une réponse, renvoie oui (True), non (False) ou None si incompris."""
        from jarvis.securite.permissions import interpreter_reponse

        self._confirmation = asyncio.get_running_loop().create_future()
        try:
            son, taux = await asyncio.to_thread(self.tts.synthetiser, question)
            self._changer_etat("parole")
            await self.sortie.jouer(son, taux)
            self._commencer_ecoute("confirmation")
            texte = await asyncio.wait_for(self._confirmation, delai_s)
        except TimeoutError:
            texte = ""
        finally:
            self._confirmation = None
            if self.etat == "confirmation":
                self._changer_etat("reflexion")
        self._emettre("confirmation", texte=texte)
        return interpreter_reponse(texte) if texte else None

    async def _transcrire_confirmation(self, son: np.ndarray) -> None:
        texte = await asyncio.to_thread(self.stt.transcrire, son.astype(np.float32) / 32768)
        if self._confirmation and not self._confirmation.done():
            self._confirmation.set_result(retirer_mot_reveil(texte))

    # --- Réponse ----------------------------------------------------------------------------

    async def _repondre(self, son: np.ndarray, mesure: Mesure) -> None:
        texte = retirer_mot_reveil(await asyncio.to_thread(self.stt.transcrire, son.astype(np.float32) / 32768))
        mesure.transcription = time.monotonic()
        mesure.texte = texte
        self._emettre("transcription", texte=texte)
        if not texte:
            self._commencer_ecoute("suite")
            return
        reussi = await self._dire(self.cerveau.repondre(texte, "voix"), mesure)
        self.mesures.append(mesure)
        if mesure.latence_ms is not None:
            log.info("Latence fin de parole -> premier son : %d ms", mesure.latence_ms)
            self._emettre("latence", ms=mesure.latence_ms)
        if reussi:
            self.vad.reinitialiser()
            self.reveil.reinitialiser()
            self._commencer_ecoute("suite")

    async def _dire(self, morceaux: AsyncIterator[str], mesure: Mesure | None = None) -> bool:
        """Synthétise et joue au fil de l'eau : la phrase n+1 est synthétisée pendant la lecture de n."""
        a_jouer: asyncio.Queue = asyncio.Queue()
        decoupeur = DecoupeurPhrases()
        complet = []

        async def produire():
            try:
                async for morceau in morceaux:
                    if mesure and not mesure.premier_texte:
                        mesure.premier_texte = time.monotonic()
                    complet.append(morceau)
                    for phrase in decoupeur.ajouter(morceau):
                        await a_jouer.put(await asyncio.to_thread(self.tts.synthetiser, phrase))
                for phrase in decoupeur.vider():
                    await a_jouer.put(await asyncio.to_thread(self.tts.synthetiser, phrase))
            finally:
                await a_jouer.put(None)

        producteur = asyncio.create_task(produire())
        try:
            while (element := await a_jouer.get()) is not None:
                son, taux = element
                if self.etat != "parole":
                    self._changer_etat("parole")
                if mesure and not mesure.premier_son:
                    mesure.premier_son = time.monotonic()
                if not await self.sortie.jouer(son, taux):
                    return False
            await producteur
            self._emettre("reponse", texte="".join(complet))
            return True
        finally:
            producteur.cancel()

    async def _traiter_annonces(self) -> None:
        while True:
            texte = await self._annonces.get()
            while self.etat not in ("veille", "suite"):
                await asyncio.sleep(0.2)

            async def flux(t=texte):
                yield t

            self._changer_etat("parole")
            await self._dire(flux())
            self._changer_etat("veille")
