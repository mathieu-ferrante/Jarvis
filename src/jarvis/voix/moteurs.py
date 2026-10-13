"""Moteurs vocaux : réveil, détection de parole, transcription, synthèse. Tous locaux, sur CPU.

Chaque moteur a une version « factice » pour les tests, sans modèle.
"""

from __future__ import annotations

import difflib
import logging
import re
import time

import numpy as np

from jarvis import modeles
from jarvis.diagnostic import audio as outils_audio
from jarvis.diagnostic.catalogue import OPENWAKEWORD

log = logging.getLogger(__name__)


# --- Détection de parole (VAD) --------------------------------------------------------------


class DetecteurParole:
    """Silero VAD (fourni avec openWakeWord). `probabilite(trame)` ∈ [0, 1]."""

    def __init__(self):
        from openwakeword.vad import VAD

        self._vad = VAD(model_path=str(modeles.chemin(OPENWAKEWORD["silero_vad"])))

    def probabilite(self, trame: np.ndarray) -> float:
        return float(self._vad.predict(trame, frame_size=640))

    def reinitialiser(self) -> None:
        self._vad.reset_states()


class DetecteurParoleEnergie:
    """Repli sans modèle (tests) : seuil d'énergie."""

    def __init__(self, seuil_dbfs: float = -45):
        self.seuil = seuil_dbfs

    def probabilite(self, trame: np.ndarray) -> float:
        return 1.0 if outils_audio.niveau_dbfs(trame) > self.seuil else 0.0

    def reinitialiser(self) -> None:
        pass


# --- Mot de réveil --------------------------------------------------------------------------

_JARVIS = re.compile(r"\b(dj?|j)a+r+v+i+(s|ce|sse|ss|x|z)?\b", re.I)


def contient_jarvis(texte: str) -> bool:
    """« Jarvis » et ses transcriptions approchées (jarvi, djarvis, jarvice…)."""
    texte = texte.lower()
    if _JARVIS.search(texte):
        return True
    return any(difflib.SequenceMatcher(None, mot, "jarvis").ratio() >= 0.8 for mot in re.findall(r"\w+", texte))


class DetecteurReveil:
    """openWakeWord « hey jarvis » en premier étage ; si le score est seulement « possible »
    (entre le seuil bas et le seuil), un second étage vérifie « Jarvis » par la transcription
    des dernières 1,6 s. C'est ce qui permet de dire « Jarvis » seul, à la française (D6)."""

    def __init__(self, seuil: float = 0.5, seuil_bas: float = 0.15, transcripteur=None):
        from openwakeword.model import Model

        self.modele = Model(
            wakeword_models=[str(modeles.chemin(OPENWAKEWORD["hey_jarvis"]))],
            melspec_model_path=str(modeles.chemin(OPENWAKEWORD["melspectrogram"])),
            embedding_model_path=str(modeles.chemin(OPENWAKEWORD["embedding"])),
            inference_framework="onnx",
        )
        self.seuil, self.seuil_bas = seuil, seuil_bas
        self.transcripteur = transcripteur
        self._historique: list[np.ndarray] = []
        self._derniere_verif = 0.0

    def reinitialiser(self) -> None:
        self.modele.reset()
        self._historique.clear()

    def traiter(self, trame: np.ndarray) -> bool:
        self._historique.append(trame)
        del self._historique[:-20]  # 1,6 s
        score = max(self.modele.predict(trame).values())
        if score >= self.seuil:
            return True
        if score >= self.seuil_bas and self.transcripteur and time.monotonic() - self._derniere_verif > 0.8:
            self._derniere_verif = time.monotonic()
            texte = self.transcripteur.transcrire(outils_audio.en_float32(np.concatenate(self._historique)))
            if contient_jarvis(texte):
                log.info("Réveil confirmé par transcription (score %.2f) : %s", score, texte)
                return True
        return False


class DetecteurReveilFactice:
    """Pour les tests : se déclenche quand l'énergie dépasse un seuil pendant `trames` trames."""

    def __init__(self, seuil_dbfs: float = -30, trames: int = 3):
        self.seuil, self.trames, self._compte = seuil_dbfs, trames, 0

    def reinitialiser(self) -> None:
        self._compte = 0

    def traiter(self, trame: np.ndarray) -> bool:
        self._compte = self._compte + 1 if outils_audio.niveau_dbfs(trame) > self.seuil else 0
        return self._compte >= self.trames


# --- Transcription --------------------------------------------------------------------------


class TranscripteurParakeet:
    """Parakeet TDT 0.6B v3 (onnx-asr, int8, CPU). Choix provisoire mesuré en J0 sur le poste de dev."""

    def __init__(self, fils: int = 4):
        import onnx_asr
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = fils
        dossier = modeles.chemin(modeles.PARAKEET_ONNX[0]).parent
        self.modele = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", dossier, quantization="int8",
                                          sess_options=options, providers=["CPUExecutionProvider"])

    def transcrire(self, son16k: np.ndarray) -> str:
        if len(son16k) < 1600:
            return ""
        return str(self.modele.recognize(outils_audio.en_float32(son16k), sample_rate=16000)).strip()


class TranscripteurFasterWhisper:
    def __init__(self, dossier: str, fils: int = 4):
        from faster_whisper import WhisperModel

        self.modele = WhisperModel(dossier, device="cpu", compute_type="int8", cpu_threads=fils,
                                   local_files_only=True)

    def transcrire(self, son16k: np.ndarray) -> str:
        segments, _ = self.modele.transcribe(outils_audio.en_float32(son16k), language="fr", beam_size=1,
                                             vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


class TranscripteurFactice:
    """Renvoie les textes fournis, dans l'ordre (tests)."""

    def __init__(self, textes: list[str]):
        self.textes = list(textes)
        self.appels = 0

    def transcrire(self, son16k: np.ndarray) -> str:
        self.appels += 1
        return self.textes.pop(0) if self.textes else ""


# --- Synthèse -------------------------------------------------------------------------------


class Synthese:
    """Piper ou Kokoro (CPU). Les phrases courtes déjà dites sont gardées en cache (« C'est fait. ») :
    elles repartent sans nouvelle synthèse (extensions §2.2, réponses préenregistrées)."""

    TAILLE_CACHE = 256
    PHRASES_COURANTES = ("C'est fait.", "D'accord.", "En pause.", "C'est reparti.", "Morceau suivant.",
                         "Laisse-moi réfléchir.", "D'accord, j'arrête tout.", "Je n'ai pas pu le faire.")

    def __init__(self, cle_voix: str, prechauffer: bool = True):
        from jarvis.diagnostic.tts import Synthetiseur

        self._synth = Synthetiseur(modeles.voix(cle_voix), modeles.dossier_pour(modeles.voix(cle_voix).fichiers[0]))
        self._cache: dict[str, tuple[np.ndarray, int]] = {}
        if prechauffer:
            for phrase in self.PHRASES_COURANTES:
                self.synthetiser(phrase)

    def synthetiser(self, texte: str) -> tuple[np.ndarray, int]:
        if texte in self._cache:
            return self._cache[texte]
        resultat = self._synth.synthetiser(texte)
        if len(texte) <= 60:
            if len(self._cache) >= self.TAILLE_CACHE:
                self._cache.pop(next(iter(self._cache)))
            self._cache[texte] = resultat
        return resultat


class SyntheseFactice:
    """Un bip par phrase, de durée proportionnelle au texte (tests)."""

    def __init__(self):
        self.phrases: list[str] = []

    def synthetiser(self, texte: str) -> tuple[np.ndarray, int]:
        self.phrases.append(texte)
        duree = 0.05 * max(len(texte), 1) / 10
        t = np.arange(int(16000 * duree)) / 16000
        return (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 16000


def creer_transcripteur(config_voix):
    if config_voix.stt == "faster-whisper":
        return TranscripteurFasterWhisper(str(modeles.chemin(modeles.PARAKEET_ONNX[0]).parent.parent
                                              / "faster-whisper-small"), config_voix.fils_stt)
    return TranscripteurParakeet(config_voix.fils_stt)
