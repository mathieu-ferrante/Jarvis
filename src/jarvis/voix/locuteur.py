"""Identification du locuteur (VOX-11) : les actions sensibles ne sont confirmées qu'à la voix de Mathieu.

Empreinte vocale (WeSpeaker ResNet34, sherpa-onnx, CPU) calculée sur chaque confirmation à la
voix, comparée à l'empreinte de référence enregistrée lors de l'enrôlement
(`python -m jarvis enroler-voix`). L'empreinte (256 nombres, pas l'audio) reste sur le PC,
chiffrée dans le coffre. Sans enrôlement, la vérification est simplement désactivée.
"""

from __future__ import annotations

import base64
import json
import logging

import numpy as np

from jarvis import modeles

log = logging.getLogger(__name__)
NOM_COFFRE = "empreinte_vocale"
SEUIL_PAR_DEFAUT = 0.62  # PROVISOIRE : recalibré à l'enrôlement sur la voix de Mathieu


def cosinus(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


class Extracteur:
    def __init__(self, fils: int = 2):
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(modeles.chemin(modeles.LOCUTEUR)),
                                                             num_threads=fils, provider="cpu")
        if not config.validate():
            raise RuntimeError("modèle d'empreinte vocale absent : python -m jarvis installer")
        self._ex = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def empreinte(self, son16k: np.ndarray) -> np.ndarray:
        flux = self._ex.create_stream()
        flux.accept_waveform(16000, np.asarray(son16k, dtype=np.float32))
        flux.input_finished()
        return np.asarray(self._ex.compute(flux), dtype=np.float32)


def calibrer(empreintes_mathieu: list[np.ndarray], empreintes_autres: list[np.ndarray] | None = None) -> dict:
    """Référence = moyenne normalisée ; seuil entre la similarité la plus basse de Mathieu et la plus
    haute des autres voix (prudent : en cas de doute, on refuse)."""
    ref = np.mean([e / np.linalg.norm(e) for e in empreintes_mathieu], axis=0)
    ref /= np.linalg.norm(ref)
    siennes = [cosinus(ref, e) for e in empreintes_mathieu]
    seuil = SEUIL_PAR_DEFAUT
    if empreintes_autres:
        autres = [cosinus(ref, e) for e in empreintes_autres]
        seuil = round(max(max(autres) + 0.03, min(min(siennes) - 0.05, (min(siennes) + max(autres)) / 2)), 3)
    return {"reference": ref, "seuil": seuil, "min_mathieu": round(min(siennes), 3)}


class VerificateurLocuteur:
    def __init__(self, coffre, extracteur: Extracteur | None = None):
        self.coffre = coffre
        self.extracteur = extracteur
        self.reference: np.ndarray | None = None
        self.seuil = SEUIL_PAR_DEFAUT
        brut = coffre.lire(NOM_COFFRE) if coffre else None
        if brut:
            d = json.loads(brut)
            self.reference = np.frombuffer(base64.b64decode(d["reference"]), dtype=np.float32)
            self.seuil = float(d["seuil"])

    @property
    def actif(self) -> bool:
        return self.reference is not None

    def enregistrer(self, calibration: dict) -> None:
        self.reference, self.seuil = calibration["reference"].astype(np.float32), calibration["seuil"]
        self.coffre.ecrire(NOM_COFFRE, json.dumps({"reference": base64.b64encode(self.reference.tobytes()).decode(),
                                                   "seuil": self.seuil}))

    def verifier(self, son16k: np.ndarray) -> tuple[bool, float]:
        """(est Mathieu, score). Sans enrôlement : toujours vrai (fonction désactivée)."""
        if not self.actif:
            return True, 1.0
        if len(son16k) < 16000 * 0.6:
            return False, 0.0  # trop court pour juger : prudence
        if self.extracteur is None:
            self.extracteur = Extracteur()
        score = cosinus(self.reference, self.extracteur.empreinte(son16k))
        return score >= self.seuil, round(score, 3)
