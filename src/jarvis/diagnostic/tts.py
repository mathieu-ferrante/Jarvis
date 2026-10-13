"""Voix de synthèse : latence jusqu'au premier son et vitesse, pour Piper et Kokoro (CPU).

Jarvis diffusera sa réponse phrase par phrase (VOX-03) : le chiffre qui compte est le temps
de synthèse de la *première phrase*, pas celui du texte entier.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np

from jarvis.diagnostic import audio
from jarvis.diagnostic.catalogue import VoixTTS

PREMIERES_PHRASES = [
    "C'est fait, le son est à trente pour cent.",
    "Il fera beau demain à Marseille, avec vingt-deux degrés l'après-midi.",
    "D'accord, je lance Spotify.",
    "Ta dernière session de deathmatch était très bonne : ton temps de réaction s'améliore.",
]
TEXTE_ECOUTE = (
    "Bonjour Mathieu. Je suis Jarvis, ton assistant personnel. Tout ce que tu me dis reste sur "
    "ton ordinateur. Aujourd'hui, tu as deux rendez-vous, et il fera beau à Marseille. "
    "Veux-tu que je lance ta playlist habituelle ?"
)


class Synthetiseur:
    """Interface commune : `synthetiser(texte) -> (audio float32, taux)`."""

    def __init__(self, voix: VoixTTS, dossier_modeles: Path):
        self.voix = voix
        chemins = [dossier_modeles / f.destination for f in voix.fichiers]
        debut = time.perf_counter()
        if voix.moteur == "piper":
            from piper import PiperVoice

            self._piper = PiperVoice.load(chemins[0], config_path=chemins[1])
            self.taux = self._piper.config.sample_rate
        elif voix.moteur == "kokoro":
            from kokoro_onnx import Kokoro

            self._kokoro = Kokoro(str(chemins[0]), str(chemins[1]))
            self.taux = 24000
        else:
            raise ValueError(voix.moteur)
        self.chargement_s = round(time.perf_counter() - debut, 2)

    def synthetiser(self, texte: str, voix: str | None = None, langue: str = "fr-fr") -> tuple[np.ndarray, int]:
        """`voix` et `langue` ne servent qu'à Kokoro (ex. voix anglaise pour un contrôle)."""
        if self.voix.moteur == "piper":
            morceaux = [m.audio_float_array for m in self._piper.synthesize(texte)]
            return (np.concatenate(morceaux) if morceaux else np.zeros(0, np.float32)), self.taux
        echantillons, taux = self._kokoro.create(texte, voice=voix or self.voix.voix, speed=1.0, lang=langue)
        return echantillons.astype(np.float32), taux


def mesurer_voix(voix: VoixTTS, dossier_modeles: Path, dossier_ecoute: Path) -> tuple[dict, Synthetiseur | None]:
    """Mesure une voix ; renvoie aussi le synthétiseur chargé, réutilisé pour fabriquer le corpus."""
    try:
        synth = Synthetiseur(voix, dossier_modeles)
        synth.synthetiser("Préchauffage.")  # la première inférence ONNX est toujours plus lente
        durees, rtf = [], []
        for phrase in PREMIERES_PHRASES:
            debut = time.perf_counter()
            son, taux = synth.synthetiser(phrase)
            duree = time.perf_counter() - debut
            durees.append(duree)
            rtf.append(duree / max(len(son) / taux, 1e-6))
        son, taux = synth.synthetiser(TEXTE_ECOUTE)
        fichier = audio.ecrire_wav(dossier_ecoute / f"{voix.cle}.wav", son, taux)
    except Exception as e:  # une voix qui plante ne doit pas arrêter le diagnostic
        return {"voix": voix.cle, "erreur": f"{type(e).__name__} : {e}"}, None
    return {
        "voix": voix.cle,
        "moteur": voix.moteur,
        "chargement_s": synth.chargement_s,
        "premiere_phrase_ms": round(1000 * statistics.median(durees)),
        "premiere_phrase_max_ms": round(1000 * max(durees)),
        "facteur_temps_reel": round(statistics.median(rtf), 3),
        "fichier_ecoute": str(fichier),
    }, synth
