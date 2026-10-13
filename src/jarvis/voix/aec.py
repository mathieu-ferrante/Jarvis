"""Annulation d'écho acoustique (VOX-13) : pour interrompre Jarvis sans casque.

Filtre adaptatif par blocs dans le domaine fréquentiel, partitionné (PBFDAF, « overlap-save ») :
il apprend le trajet haut-parleurs → pièce → micro et retire du micro le son que Jarvis joue
lui-même. Longueur couverte : 16 partitions × 256 échantillons = 256 ms (latence de la carte son
et réverbération d'une pièce). Coût : quelques % d'un cœur, uniquement quand Jarvis parle.
"""

from __future__ import annotations

from collections import deque

import numpy as np

BLOC = 256


class AnnuleurEcho:
    def __init__(self, partitions: int = 16, pas: float = 0.5, lissage: float = 0.9):
        self.M, self.mu, self.beta = partitions, pas, lissage
        self.W = np.zeros((partitions, BLOC + 1), dtype=np.complex128)
        self.X = np.zeros((partitions, BLOC + 1), dtype=np.complex128)  # spectres des derniers blocs de référence
        self.P = np.full(BLOC + 1, 1e-3)
        self._ref_prec = np.zeros(BLOC)

    def reinitialiser(self) -> None:
        self.__init__(self.M, self.mu, self.beta)

    def _bloc(self, micro: np.ndarray, reference: np.ndarray) -> np.ndarray:
        x2 = np.concatenate([self._ref_prec, reference])
        self._ref_prec = reference
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = np.fft.rfft(x2)
        y = np.fft.irfft((self.W * self.X).sum(axis=0))[BLOC:]
        erreur = micro - y
        Ef = np.fft.rfft(np.concatenate([np.zeros(BLOC), erreur]))
        # Normalisation par l'énergie de toutes les partitions (sinon les M mises à jour s'additionnent)
        self.P = self.beta * self.P + (1 - self.beta) * np.sum(np.abs(self.X) ** 2, axis=0)
        if np.max(np.abs(reference)) > 1e-4:  # n'apprend que quand Jarvis parle
            gradient = self.mu * np.conj(self.X) * Ef / (self.P + 1e-6)
            self.W += gradient
            # Contrainte de gradient : filtre causal de BLOC coefficients par partition
            w = np.fft.irfft(self.W, axis=1)
            w[:, BLOC:] = 0
            self.W = np.fft.rfft(w, axis=1)
        return erreur

    def traiter(self, micro: np.ndarray, reference: np.ndarray) -> np.ndarray:
        """`micro` et `reference` : même longueur (multiple de 256), float32 dans [-1, 1]."""
        sortie = np.empty_like(micro, dtype=np.float64)
        for i in range(0, len(micro), BLOC):
            sortie[i:i + BLOC] = self._bloc(micro[i:i + BLOC].astype(np.float64),
                                            reference[i:i + BLOC].astype(np.float64))
        return sortie.astype(np.float32)


class FileReference:
    """Ce que Jarvis joue, en 16 kHz, consommé au rythme des trames du micro."""

    def __init__(self, max_s: float = 30.0):
        self._tampon: deque[np.ndarray] = deque()
        self._taille = 0
        self.max = int(16000 * max_s)

    def ajouter(self, son16k: np.ndarray) -> None:
        self._tampon.append(np.asarray(son16k, dtype=np.float32))
        self._taille += len(son16k)
        while self._taille > self.max:
            self._taille -= len(self._tampon.popleft())

    def vider(self) -> None:
        self._tampon.clear()
        self._taille = 0

    def prendre(self, n: int) -> np.ndarray:
        sortie = np.zeros(n, dtype=np.float32)
        rempli = 0
        while rempli < n and self._tampon:
            bloc = self._tampon[0]
            k = min(n - rempli, len(bloc))
            sortie[rempli:rempli + k] = bloc[:k]
            rempli += k
            if k == len(bloc):
                self._tampon.popleft()
            else:
                self._tampon[0] = bloc[k:]
        self._taille -= rempli
        return sortie
