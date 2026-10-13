"""Outils audio du diagnostic : rééchantillonnage, bruit de PC de jeu simulé, fichiers WAV."""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np

TAUX_STT = 16000  # Whisper et openWakeWord attendent du 16 kHz mono


def en_float32(audio: np.ndarray) -> np.ndarray:
    if audio.dtype == np.int16:
        return audio.astype(np.float32) / 32768.0
    return audio.astype(np.float32)


def en_int16(audio: np.ndarray) -> np.ndarray:
    if audio.dtype == np.int16:
        return audio
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def reechantillonner(audio: np.ndarray, taux_source: int, taux_cible: int = TAUX_STT) -> np.ndarray:
    audio = en_float32(audio)
    if taux_source == taux_cible:
        return audio
    from scipy.signal import resample_poly

    g = gcd(taux_source, taux_cible)
    return resample_poly(audio, taux_cible // g, taux_source // g).astype(np.float32)


def bruit_pc(duree_echantillons: int, taux: int = TAUX_STT, graine: int = 0) -> np.ndarray:
    """Bruit de ventilateur simulé : bruit rose + ronflement à 120 Hz et ses harmoniques."""
    rng = np.random.default_rng(graine)
    blanc = rng.standard_normal(duree_echantillons)
    # Bruit rose par filtrage spectral en 1/sqrt(f)
    spectre = np.fft.rfft(blanc)
    f = np.fft.rfftfreq(duree_echantillons, 1 / taux)
    f[0] = f[1] if len(f) > 1 else 1.0
    rose = np.fft.irfft(spectre / np.sqrt(f), n=duree_echantillons)
    t = np.arange(duree_echantillons) / taux
    ronflement = sum(np.sin(2 * np.pi * 120 * k * t + k) / k for k in (1, 2, 3))
    bruit = rose / (np.std(rose) + 1e-9) + 0.3 * ronflement
    return (bruit / (np.std(bruit) + 1e-9)).astype(np.float32)


def melanger(parole: np.ndarray, bruit: np.ndarray, rsb_db: float) -> np.ndarray:
    """Ajoute `bruit` à `parole` avec le rapport signal sur bruit demandé (en dB)."""
    parole = en_float32(parole)
    bruit = bruit[: len(parole)]
    p_parole = np.mean(parole**2) + 1e-12
    p_bruit = np.mean(bruit**2) + 1e-12
    gain = np.sqrt(p_parole / (p_bruit * 10 ** (rsb_db / 10)))
    melange = parole + gain * bruit
    crete = np.max(np.abs(melange))
    return (melange / crete * 0.9 if crete > 0.99 else melange).astype(np.float32)


def silence(secondes: float, taux: int = TAUX_STT) -> np.ndarray:
    return np.zeros(int(secondes * taux), dtype=np.float32)


def ecrire_wav(chemin: Path, audio: np.ndarray, taux: int) -> Path:
    import soundfile as sf

    chemin.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(chemin), en_int16(audio), taux, subtype="PCM_16")
    return chemin


def lire_wav(chemin: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    audio, taux = sf.read(str(chemin), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32), taux


def niveau_dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(en_float32(audio) ** 2)) + 1e-12)
    return round(20 * np.log10(rms), 1)
