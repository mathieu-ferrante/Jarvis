"""Mode jeu (VOX-07, NF-03, PERF-08, PERF-10) : détecter une partie et laisser le GPU au jeu.

En jeu :
- le modèle principal quitte la VRAM ; un petit modèle prend le relais sur CPU (PERF-10 : la
  VRAM est libérée dès l'arrêt du serveur, en moins d'une seconde) ;
- Jarvis et son serveur passent en priorité basse, sur des cœurs réservés (affinité) ;
- Jarvis ne parle que si on lui parle, sauf alertes autorisées (rappels).
Le retour au mode normal attend 30 s sans jeu, pour ne pas basculer entre deux parties.
"""

from __future__ import annotations

import asyncio
import logging
import time

import psutil

from jarvis.llm.serveur import Lancement

log = logging.getLogger(__name__)
DELAI_SORTIE_S = 30


def coeurs_reserves(nombre: int = 4) -> list[int]:
    """Les derniers cœurs logiques (les jeux chargent surtout les premiers)."""
    total = psutil.cpu_count(logical=True) or 1
    return list(range(max(0, total - nombre), total))


def regler_processus(pid: int, en_jeu: bool) -> None:
    try:
        p = psutil.Process(pid)
        if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if en_jeu else psutil.NORMAL_PRIORITY_CLASS)
        p.cpu_affinity(coeurs_reserves() if en_jeu else list(range(psutil.cpu_count(logical=True) or 1)))
    except (psutil.Error, OSError, AttributeError):
        log.debug("Réglage du processus %s impossible", pid)


class DetecteurJeu:
    def __init__(self, jarvis, intervalle_s: float = 3.0):
        self.jarvis = jarvis
        self.intervalle_s = intervalle_s
        self._derniere_vue = 0.0
        self.executables = {e.lower() for e in jarvis.config.jeu.executables}

    def jeu_en_cours(self) -> str | None:
        for p in psutil.process_iter(["name"]):
            nom = (p.info["name"] or "").lower()
            if nom in self.executables:
                return p.info["name"]
        return None

    async def entrer(self, jeu: str) -> None:
        j = self.jarvis
        debut = time.monotonic()
        j.etat_jeu.update(en_jeu=True, jeu=jeu)
        log.info("Mode jeu : %s", jeu)
        regler_processus(psutil.Process().pid, True)
        c = j.config.llm
        if j.avec_modeles and not c.url_externe:
            await j.serveur_llm.arreter()  # VRAM libérée ici
            j.bus.publier("jeu", etat="vram_liberee", ms=round(1000 * (time.monotonic() - debut)))
            try:
                await j.serveur_llm.demarrer(Lancement(c.mode_jeu, "cpu", c.port, 8192, cpu_seul=True, vision=False,
                                                       cache_kv=c.cache_kv))
                if j.serveur_llm.processus:
                    regler_processus(j.serveur_llm.processus.pid, True)
                # Préfixe réduit (outils de jeu) mis en cache pendant le chargement de la partie :
                # la 1re question en jeu n'attend pas l'évaluation du prompt sur CPU
                if hasattr(j, "prechauffer"):
                    await j.prechauffer()
            except Exception:  # noqa: BLE001
                log.exception("Modèle de mode jeu non démarré")
        j.bus.publier("jeu", etat="actif", jeu=jeu, bascule_ms=round(1000 * (time.monotonic() - debut)))

    async def sortir(self) -> None:
        j = self.jarvis
        j.etat_jeu.update(en_jeu=False, jeu=None)
        log.info("Fin du mode jeu")
        regler_processus(psutil.Process().pid, False)
        if j.avec_modeles and not j.config.llm.url_externe:
            await j.demarrer_modeles()
        j.bus.publier("jeu", etat="inactif")

    async def boucle(self) -> None:
        if not self.jarvis.config.jeu.detection:
            return
        while True:
            jeu = await asyncio.to_thread(self.jeu_en_cours)
            if jeu:
                self._derniere_vue = time.monotonic()
                if not self.jarvis.etat_jeu["en_jeu"]:
                    await self.entrer(jeu)
            elif self.jarvis.etat_jeu["en_jeu"] and time.monotonic() - self._derniere_vue > DELAI_SORTIE_S:
                await self.sortir()
            await asyncio.sleep(self.intervalle_s)
