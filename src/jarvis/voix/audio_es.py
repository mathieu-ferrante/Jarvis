"""Entrée micro et sortie haut-parleurs, réelles ou simulées (tests et poste de développement).

L'entrée produit des trames de 80 ms en 16 kHz mono int16 (format attendu par openWakeWord,
Silero et Parakeet). La sortie joue de l'audio et peut être coupée net (interruption, VOX-04).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from jarvis.diagnostic import audio as outils_audio

TAUX = 16000
TRAME = 1280  # 80 ms


class EntreeAudio:
    async def trames(self) -> AsyncIterator[np.ndarray]:  # pragma: no cover - interface
        raise NotImplementedError
        yield

    def fermer(self) -> None:
        pass


class Micro(EntreeAudio):
    """Micro réel via sounddevice. Le son ne quitte jamais ce processus."""

    def __init__(self, peripherique: str | int | None = None):
        self.peripherique = int(peripherique) if str(peripherique or "").isdigit() else (peripherique or None)
        self._flux = None

    async def trames(self) -> AsyncIterator[np.ndarray]:
        import sounddevice as sd

        boucle = asyncio.get_running_loop()
        file: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        info = sd.query_devices(self.peripherique, kind="input")
        taux_natif = int(info["default_samplerate"])
        reste = np.zeros(0, dtype=np.float32)

        def rappel(donnees, _n, _t, _statut):
            boucle.call_soon_threadsafe(_deposer, donnees[:, 0].copy())

        def _deposer(bloc):
            if not file.full():
                file.put_nowait(bloc)

        self._flux = sd.InputStream(device=self.peripherique, channels=1, samplerate=taux_natif,
                                    dtype="float32", blocksize=int(taux_natif * 0.08), callback=rappel)
        self._flux.start()
        try:
            while True:
                bloc = await file.get()
                reste = np.concatenate([reste, outils_audio.reechantillonner(bloc, taux_natif, TAUX)])
                while len(reste) >= TRAME:
                    yield outils_audio.en_int16(reste[:TRAME])
                    reste = reste[TRAME:]
        finally:
            self.fermer()

    def fermer(self) -> None:
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None


class EntreeSimulee(EntreeAudio):
    """Micro simulé : une suite de fichiers WAV ou de tableaux, puis du silence.

    `temps_reel=False` déroule aussi vite que possible (tests)."""

    def __init__(self, morceaux: list[Path | np.ndarray], temps_reel: bool = False, silence_final_s: float = 3.0,
                 bruit: float = 0.0):
        self.morceaux = morceaux
        self.temps_reel = temps_reel
        self.silence_final_s = silence_final_s
        self.bruit = bruit
        self.injection: asyncio.Queue[np.ndarray] = asyncio.Queue()

    def injecter(self, son: np.ndarray) -> None:
        """Ajoute de l'audio pendant le déroulement (ex. une interruption pendant que Jarvis parle)."""
        self.injection.put_nowait(son)

    def _flux_complet(self) -> np.ndarray:
        parties = []
        for m in self.morceaux:
            if isinstance(m, Path):
                son, taux = outils_audio.lire_wav(m)
                m = outils_audio.reechantillonner(son, taux, TAUX)
            parties.append(outils_audio.en_float32(m))
        parties.append(np.zeros(int(self.silence_final_s * TAUX), dtype=np.float32))
        return np.concatenate(parties)

    async def trames(self) -> AsyncIterator[np.ndarray]:
        tout = self._flux_complet()
        rng = np.random.default_rng(0)
        i = 0
        injecte = np.zeros(0, dtype=np.float32)
        while i + TRAME <= len(tout) or len(injecte) or not self.injection.empty():
            while not self.injection.empty():
                injecte = np.concatenate([injecte, outils_audio.en_float32(self.injection.get_nowait())])
            if len(injecte) >= TRAME:
                trame, injecte = injecte[:TRAME], injecte[TRAME:]
            elif i + TRAME <= len(tout):
                trame = tout[i:i + TRAME]
                i += TRAME
            elif len(injecte):  # reste injecté plus court qu'une trame : complété par du silence
                trame = np.pad(injecte, (0, TRAME - len(injecte)))
                injecte = np.zeros(0, dtype=np.float32)
            else:
                break
            if self.bruit:
                trame = trame + rng.normal(0, self.bruit, TRAME).astype(np.float32)
            yield outils_audio.en_int16(trame)
            await asyncio.sleep(0.08 if self.temps_reel else 0)


class SortieAudio:
    """Lecture avec coupure immédiate. `jouer` attend la fin (ou la coupure)."""

    def __init__(self, peripherique: str | int | None = None):
        self.peripherique = int(peripherique) if str(peripherique or "").isdigit() else (peripherique or None)
        self._coupe = threading.Event()
        self.en_cours = False

    async def jouer(self, son: np.ndarray, taux: int) -> bool:
        """Joue `son`. Renvoie False si la lecture a été coupée."""
        import sounddevice as sd

        self._coupe.clear()
        self.en_cours = True
        son = outils_audio.en_float32(son)
        position = 0
        fini = asyncio.Event()
        boucle = asyncio.get_running_loop()

        def rappel(sortie, n, _t, _statut):
            nonlocal position
            if self._coupe.is_set():
                sortie[:] = 0
                raise sd.CallbackStop
            morceau = son[position:position + n]
            sortie[:len(morceau), 0] = morceau
            sortie[len(morceau):, 0] = 0
            position += n
            if position >= len(son):
                raise sd.CallbackStop

        flux = sd.OutputStream(device=self.peripherique, samplerate=taux, channels=1, dtype="float32",
                               callback=rappel, finished_callback=lambda: boucle.call_soon_threadsafe(fini.set))
        with flux:
            await fini.wait()
        self.en_cours = False
        return not self._coupe.is_set()

    def couper(self) -> None:
        self._coupe.set()


class SortieSimulee(SortieAudio):
    """Sortie simulée : enregistre ce qui aurait été joué et simule sa durée."""

    def __init__(self, vitesse: float = 0.0):
        super().__init__()
        self.joue: list[tuple[np.ndarray, int]] = []
        self.coupures = 0
        self.vitesse = vitesse  # 0 = instantané ; 1 = temps réel

    async def jouer(self, son: np.ndarray, taux: int) -> bool:
        self._coupe.clear()
        self.en_cours = True
        self.joue.append((son, taux))
        duree = len(son) / taux * self.vitesse
        pas = 0.02
        ecoule = 0.0
        try:
            while ecoule < duree:
                if self._coupe.is_set():
                    break
                await asyncio.sleep(pas)
                ecoule += pas
        except asyncio.CancelledError:  # tâche de réponse annulée pendant la lecture
            self.coupures += 1
            self.en_cours = False
            raise
        await asyncio.sleep(0)
        self.en_cours = False
        if self._coupe.is_set():
            self.coupures += 1
            return False
        return True
