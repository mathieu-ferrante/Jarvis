"""Mot de réveil « Jarvis » personnalisé (VOX-10, lot J16) : entraînement local, sur CPU.

    python -m jarvis entrainer-reveil [--enregistrements DOSSIER] [--ambiance DOSSIER]

Exemples positifs : enregistrements de Mathieu (s'il y en a) + prononciations françaises
synthétiques (toutes les voix Piper / Kokoro installées, vitesses variées), augmentés (bruit
de PC, réverbération, volume, décalage). Négatifs : phrases phonétiquement proches, bruit
seul, ambiances de jeu enregistrées. Représentations : les modèles figés d'openWakeWord
(spectrogramme + « speech_embedding ») ; classifieur : petit réseau (1 536 → 64 → 1) entraîné
en NumPy, exporté en ONNX au format attendu par openWakeWord ([1, 16, 96] → [1, 1]) : le même
fichier sert au PC et au téléphone (TEL-02).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvis import chemins, modeles
from jarvis.diagnostic import audio
from jarvis.diagnostic.catalogue import OPENWAKEWORD, VOIX_TTS

log = logging.getLogger(__name__)
FENETRE = 16  # plongements par exemple (≈ 1,28 s)

POSITIFS = ["Jarvis", "Jarvis !", "Jarvis ?", "Jarvis.", "Hé Jarvis", "Dis Jarvis", "Jarvis, tu es là ?",
            "Ok Jarvis", "Jarvis, s'il te plaît", "Allez Jarvis"]
NEGATIFS = [
    "Le jardin est magnifique ce matin.", "J'arrive dans cinq minutes.", "Gervais est passé hier soir.",
    "C'est un garçon très gentil.", "On part à Paris demain.", "Le service client a rappelé.", "Jarnac est une petite ville.",
    "Il faut arroser le jardin.", "J'ai vu ça à la télé.", "Il est parti en vacances.", "Tu as vu la partie d'hier ?",
    "Je vais jouer en deathmatch.", "Passe-moi le sel s'il te plaît.", "Quelle heure est-il ?", "Lance la musique.",
    "Il fait beau à Marseille.", "Le chat dort sur le canapé.", "On joue en premier ce soir ?", "Rush B, rush B !",
    "Attention, il est derrière toi.", "Je n'ai plus de munitions.", "Bien joué les gars.", "Ça va, et toi ?",
    "J'ai faim, on mange quoi ?", "Il y a un sniper à mid.", "Je change d'arme.", "Javel et vinaigre, attention.",
    "Charvieu est près de Lyon.", "La gare est fermée.", "Jardiner me détend.", "Arvis, c'est un prénom ?",
    "J'avais oublié mes clés.", "Je vais voir.", "Tu viens jouer ?", "Garde la position.", "Pas mal du tout.",
]


PIEGES = ["J'arrive.", "Gervais !", "Jardin.", "Charvis ?", "J'avais dit.", "Jarnac.", "Garçon !", "Javel.",
          "Ça arrive.", "Harvey !", "Davis.", "Service.", "J'ai vu.", "Jarre.", "Paris."]


@dataclass
class Corpus:
    positifs: list[np.ndarray]
    negatifs: list[np.ndarray]


# --- Données --------------------------------------------------------------------------------


def _reverb(son: np.ndarray, rng) -> np.ndarray:
    longueur = int(16000 * rng.uniform(0.05, 0.3))
    rir = rng.standard_normal(longueur) * np.exp(-np.arange(longueur) / (longueur / 4))
    rir[0] = 1.0
    sortie = np.convolve(son, rir * rng.uniform(0.05, 0.25))[: len(son)]
    sortie[: len(son)] += son
    return sortie / (np.max(np.abs(sortie)) + 1e-9) * np.max(np.abs(son))


def augmenter(son: np.ndarray, rng, bruit: np.ndarray) -> np.ndarray:
    son = son * rng.uniform(0.3, 1.0)
    if rng.random() < 0.5:
        son = _reverb(son, rng)
    if rng.random() < 0.8:
        debut = rng.integers(0, max(1, len(bruit) - len(son)))
        son = audio.melanger(son, bruit[debut:debut + len(son)], rng.uniform(3, 25))
    return son.astype(np.float32)


def placer_en_fin(son: np.ndarray, rng, duree_s: float = 2.0) -> np.ndarray:
    """Le mot se termine vers la fin de l'extrait (comme en écoute continue)."""
    total = int(16000 * duree_s)
    son = son[-total + 1600:] if len(son) > total - 1600 else son
    fin_silence = int(rng.uniform(0.05, 0.25) * 16000)
    sortie = np.zeros(total, dtype=np.float32)
    debut = max(0, total - fin_silence - len(son))
    sortie[debut:debut + len(son)] = son[: total - debut]
    return sortie


def voix_disponibles() -> list:
    """Synthétiseurs installés (Piper : plusieurs vitesses ; Kokoro : voix françaises et anglaises)."""
    from jarvis.diagnostic.tts import Synthetiseur

    voix = []
    for v in VOIX_TTS:
        if all(modeles.chemin(f).exists() for f in v.fichiers) and v.cle != "kokoro-ff_siwis-fp32":
            try:
                voix.append(Synthetiseur(v, modeles.dossier_pour(v.fichiers[0])))
            except Exception:  # noqa: BLE001
                log.warning("Voix %s inutilisable", v.cle)
    return voix


def synthetiser_varie(synth, texte: str, rng) -> list[np.ndarray]:
    sorties = []
    if synth.voix.moteur == "piper":
        from piper import SynthesisConfig

        for _ in range(3):
            cfg = SynthesisConfig(length_scale=float(rng.uniform(0.8, 1.35)), noise_scale=float(rng.uniform(0.4, 0.9)),
                                  noise_w_scale=float(rng.uniform(0.5, 1.0)))
            morceaux = [m.audio_float_array for m in synth._piper.synthesize(texte, syn_config=cfg)]
            if morceaux:
                sorties.append(audio.reechantillonner(np.concatenate(morceaux), synth.taux))
    else:
        for voix, langue in (("ff_siwis", "fr-fr"), ("am_adam", "en-us"), ("bm_george", "en-gb"), ("af_heart", "en-us")):
            try:
                son, taux = synth.synthetiser(texte, voix=voix, langue=langue)
                sorties.append(audio.reechantillonner(son, taux))
            except Exception:  # noqa: BLE001
                continue
    return sorties


def construire_corpus(enregistrements: Path | None = None, ambiance: Path | None = None, graine: int = 0,
                      repetitions: int = 4) -> Corpus:
    rng = np.random.default_rng(graine)
    bruit = audio.bruit_pc(16000 * 60, graine=graine)
    if ambiance and ambiance.exists():  # ambiances de jeu de Mathieu : meilleur bruit possible
        sons = [audio.reechantillonner(*audio.lire_wav(f)) for f in sorted(ambiance.glob("*.wav"))]
        if sons:
            bruit = np.concatenate([bruit, *sons]).astype(np.float32)
    bruts_pos, bruts_neg = [], []
    for synth in voix_disponibles():
        for texte in POSITIFS:
            bruts_pos += synthetiser_varie(synth, texte, rng)
        for texte in NEGATIFS:
            bruts_neg += synthetiser_varie(synth, texte, rng)[:1]
        for texte in PIEGES:  # sonorités proches de « Jarvis » : trois fois plus présentes
            bruts_neg += synthetiser_varie(synth, texte, rng)[:3]
    if enregistrements and enregistrements.exists():
        for f in sorted(enregistrements.glob("*.wav")):
            son, taux = audio.lire_wav(f)
            bruts_pos += [audio.reechantillonner(son, taux)] * 3  # la vraie voix compte triple
    positifs = [augmenter(placer_en_fin(s, rng), rng, bruit) for s in bruts_pos for _ in range(repetitions)]
    negatifs = [augmenter(placer_en_fin(s, rng), rng, bruit) for s in bruts_neg for _ in range(repetitions)]
    for _ in range(len(negatifs) // 3):  # bruit seul
        debut = rng.integers(0, len(bruit) - 32000)
        negatifs.append((bruit[debut:debut + 32000] * rng.uniform(0.01, 0.3)).astype(np.float32))
    # Bruit blanc à plusieurs niveaux et silence numérique : openWakeWord remplit sa mémoire tampon
    # de bruit blanc à chaque réinitialisation ; sans ces exemples, le modèle s'y déclenche.
    for niveau in (0.0, 0.001, 0.01, 0.03, 0.05, 0.1, 0.3):
        for _ in range(max(4, len(negatifs) // 40)):
            negatifs.append((rng.uniform(-1, 1, 32000) * niveau).astype(np.float32))
    return Corpus(positifs, negatifs)


# --- Représentations ------------------------------------------------------------------------


class Representations:
    def __init__(self):
        from openwakeword.utils import AudioFeatures

        self._af = AudioFeatures(melspec_model_path=str(modeles.chemin(OPENWAKEWORD["melspectrogram"])),
                                 embedding_model_path=str(modeles.chemin(OPENWAKEWORD["embedding"])),
                                 inference_framework="onnx")

    def fenetres(self, son: np.ndarray, toutes: bool = False) -> np.ndarray:
        """Fenêtres de 16 plongements, calculées EN FLUX comme pendant l'écoute (le calcul en bloc
        d'openWakeWord donne des valeurs différentes, d'environ 40 %) : la dernière (positifs), ou
        toutes, y compris celles qui chevauchent la mémoire tampon de démarrage (négatifs)."""
        self._af.reset()
        pcm = audio.en_int16(son)
        n = 0
        for i in range(0, len(pcm) - 1279, 1280):
            self._af(pcm[i:i + 1280])
            n += 1
        tampon = np.asarray(self._af.feature_buffer, dtype=np.float32)
        if not toutes:  # les 3 dernières fenêtres : le mot vient de finir, à 80 ms près
            if n < FENETRE + 2:
                return np.zeros((0, FENETRE, 96), dtype=np.float32)
            return np.stack([tampon[len(tampon) - FENETRE - k:len(tampon) - k] for k in range(3)])
        debut = max(0, tampon.shape[0] - n - FENETRE // 2)  # inclut le raccord avec le tampon de démarrage
        return np.stack([tampon[i:i + FENETRE] for i in range(debut, tampon.shape[0] - FENETRE + 1, 2)])


# --- Modèle ---------------------------------------------------------------------------------


class Reseau:
    """1 536 → 64 → 1, ReLU puis sigmoïde, entraîné par Adam sur l'entropie croisée pondérée."""

    def __init__(self, cachee: int = 64, graine: int = 0):
        rng = np.random.default_rng(graine)
        self.W1 = (rng.standard_normal((FENETRE * 96, cachee)) * np.sqrt(2 / (FENETRE * 96))).astype(np.float32)
        self.b1 = np.zeros(cachee, dtype=np.float32)
        self.W2 = (rng.standard_normal((cachee, 1)) * np.sqrt(1 / cachee)).astype(np.float32)
        self.b2 = np.zeros(1, dtype=np.float32)

    def predire(self, X: np.ndarray) -> np.ndarray:
        h = np.maximum(X.reshape(len(X), -1) @ self.W1 + self.b1, 0)
        return 1 / (1 + np.exp(-np.clip((h @ self.W2 + self.b2)[:, 0], -40, 40)))

    def entrainer(self, X: np.ndarray, y: np.ndarray, epoques: int = 40, lot: int = 128, pas: float = 1e-3,
                  poids_negatif: float = 3.0, graine: int = 0) -> list[float]:
        rng = np.random.default_rng(graine)
        params = [self.W1, self.b1, self.W2, self.b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        pertes, t = [], 0
        Xp = X.reshape(len(X), -1)
        for _ in range(epoques):
            ordre = rng.permutation(len(X))
            total = 0.0
            for i in range(0, len(X), lot):
                idx = ordre[i:i + lot]
                xb, yb = Xp[idx], y[idx]
                pois = np.where(yb > 0.5, 1.0, poids_negatif)  # un faux déclenchement coûte plus cher
                h_lin = xb @ self.W1 + self.b1
                h = np.maximum(h_lin, 0)
                p = 1 / (1 + np.exp(-np.clip((h @ self.W2 + self.b2)[:, 0], -40, 40)))
                total += float(-np.sum(pois * (yb * np.log(p + 1e-7) + (1 - yb) * np.log(1 - p + 1e-7))))
                g = (pois * (p - yb))[:, None] / len(idx)
                gW2, gb2 = h.T @ g, g.sum(0)
                gh = (g @ self.W2.T) * (h_lin > 0)
                gW1, gb1 = xb.T @ gh, gh.sum(0)
                t += 1
                for k, (param, grad) in enumerate(zip(params, [gW1, gb1, gW2, gb2], strict=True)):
                    m[k] = 0.9 * m[k] + 0.1 * grad
                    v[k] = 0.999 * v[k] + 0.001 * grad**2
                    param -= pas * (m[k] / (1 - 0.9**t)) / (np.sqrt(v[k] / (1 - 0.999**t)) + 1e-8)
            pertes.append(total / len(X))
        return pertes

    def exporter_onnx(self, chemin: Path) -> Path:
        import onnx
        from onnx import TensorProto, helper, numpy_helper

        noeuds = [
            helper.make_node("Reshape", ["x", "forme"], ["plat"]),
            helper.make_node("Gemm", ["plat", "W1", "b1"], ["h1"]),
            helper.make_node("Relu", ["h1"], ["h"]),
            helper.make_node("Gemm", ["h", "W2", "b2"], ["logit"]),
            helper.make_node("Sigmoid", ["logit"], ["score"]),
        ]
        initialiseurs = [numpy_helper.from_array(np.array([1, FENETRE * 96], dtype=np.int64), "forme"),
                         numpy_helper.from_array(self.W1, "W1"), numpy_helper.from_array(self.b1, "b1"),
                         numpy_helper.from_array(self.W2, "W2"), numpy_helper.from_array(self.b2, "b2")]
        graphe = helper.make_graph(noeuds, "jarvis_perso",
                                   [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, FENETRE, 96])],
                                   [helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1])], initialiseurs)
        modele = helper.make_model(graphe, opset_imports=[helper.make_opsetid("", 13)], producer_name="jarvis")
        modele.ir_version = 8  # lisible par ONNX Runtime Android et openWakeWord
        onnx.checker.check_model(modele)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        onnx.save(modele, str(chemin))
        return chemin


def chemin_modele_perso() -> Path:
    return chemins.dossier_modeles() / "reveil" / "jarvis_perso.onnx"


def entrainer(corpus: Corpus, sortie: Path | None = None, graine: int = 0) -> dict:
    rep = Representations()
    Xp = np.concatenate([rep.fenetres(s) for s in corpus.positifs])
    Xn = np.concatenate([rep.fenetres(s, toutes=True) for s in corpus.negatifs])
    rng = np.random.default_rng(graine)
    test_p, test_n = rng.random(len(Xp)) < 0.2, rng.random(len(Xn)) < 0.2
    X = np.concatenate([Xp[~test_p], Xn[~test_n]])
    y = np.concatenate([np.ones((~test_p).sum()), np.zeros((~test_n).sum())]).astype(np.float32)
    reseau = Reseau(graine=graine)
    pertes = reseau.entrainer(X, y, graine=graine)
    sp, sn = reseau.predire(Xp[test_p]), reseau.predire(Xn[test_n])
    # Seuil : le plus bas qui garde moins de 0,5 % de fenêtres négatives au-dessus
    seuil = float(min(0.9, max(0.5, np.quantile(sn, 0.995) + 0.02))) if len(sn) else 0.5
    metriques = {
        "positifs": int(len(Xp)), "negatifs": int(len(Xn)),
        "detection": round(float((sp >= seuil).mean()), 3) if len(sp) else None,
        "faux_par_fenetre": round(float((sn >= seuil).mean()), 4) if len(sn) else None,
        "seuil": round(seuil, 3), "perte_finale": round(pertes[-1], 4),
    }
    # Fenêtres négatives espacées de 2 plongements (160 ms) : estimation des faux déclenchements par heure
    if metriques["faux_par_fenetre"] is not None:
        metriques["faux_par_heure_estimes"] = round(metriques["faux_par_fenetre"] * 3600 / 0.16, 1)
    sortie = reseau.exporter_onnx(sortie or chemin_modele_perso())
    sortie.with_suffix(".json").write_text(json.dumps(metriques, indent=2), "utf-8")
    metriques["fichier"] = str(sortie)
    return metriques
