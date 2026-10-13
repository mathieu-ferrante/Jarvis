"""Mot de réveil : coût CPU et détections d'openWakeWord (modèle pré-entraîné « hey jarvis »).

Le cahier des charges demande « Jarvis » seul. Aucun modèle pré-entraîné « Jarvis » n'existe
pour openWakeWord : on mesure « hey jarvis » (provisoire) et on vérifie s'il réagit aussi à
« Jarvis » prononcé seul. Un modèle dédié sera entraîné en J1 si nécessaire.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import psutil

from jarvis.diagnostic import audio
from jarvis.diagnostic.catalogue import OPENWAKEWORD

SEUIL = 0.5
TRAME = 1280  # 80 ms à 16 kHz
POSITIFS = ["Hey Jarvis !", "Hey Jarvis, tu es là ?"]
SEUL = ["Jarvis !", "Jarvis, tu m'entends ?"]
NEGATIFS = [
    "Lance Spotify et mets ma playlist de concentration.",
    "J'ai joué toute la soirée avec les gars sur Discord.",
    "Il faut que je pense à acheter du pain demain.",
    "Le service client m'a rappelé ce matin.",
]


def charger(dossier_modeles: Path):
    from openwakeword.model import Model

    return Model(
        wakeword_models=[str(dossier_modeles / OPENWAKEWORD["hey_jarvis"].destination)],
        melspec_model_path=str(dossier_modeles / OPENWAKEWORD["melspectrogram"].destination),
        embedding_model_path=str(dossier_modeles / OPENWAKEWORD["embedding"].destination),
        inference_framework="onnx",
    )


def score_max(modele, son16k: np.ndarray) -> float:
    """Score maximal du mot de réveil sur un extrait, en flux par trames de 80 ms."""
    modele.reset()
    pcm = audio.en_int16(son16k)
    meilleur = 0.0
    for i in range(0, len(pcm) - TRAME + 1, TRAME):
        scores = modele.predict(pcm[i:i + TRAME])
        meilleur = max(meilleur, max(scores.values()))
    return round(float(meilleur), 3)


def cout_cpu(modele, secondes: int = 60) -> dict:
    """Temps CPU consommé par seconde d'audio écouté (le mot de réveil tourne en permanence)."""
    son = audio.en_int16(audio.bruit_pc(audio.TAUX_STT * secondes) * 0.05)
    modele.reset()
    debut_cpu, debut = time.process_time(), time.perf_counter()
    for i in range(0, len(son) - TRAME + 1, TRAME):
        modele.predict(son[i:i + TRAME])
    cpu = time.process_time() - debut_cpu
    coeurs = psutil.cpu_count(logical=True) or 1
    return {
        "pct_d_un_coeur": round(100 * cpu / secondes, 2),
        "pct_cpu_total": round(100 * cpu / secondes / coeurs, 2),
        "duree_traitement_s": round(time.perf_counter() - debut, 2),
    }


def mesurer(dossier_modeles: Path, synthetiseurs: list, enregistrements: list[dict]) -> dict:
    try:
        modele = charger(dossier_modeles)
    except Exception as e:
        return {"erreur": f"{type(e).__name__} : {e}"}
    bruit = audio.bruit_pc(audio.TAUX_STT * 10, graine=3)

    def extrait(synth, texte: str, bruite: bool) -> np.ndarray:
        son, taux = synth.synthetiser(texte)
        son = np.concatenate([audio.silence(1.0), audio.reechantillonner(son, taux), audio.silence(1.0)])
        return audio.melanger(son, np.resize(bruit, len(son)), 10) if bruite else son

    def campagne(textes: list[str]) -> list[float]:
        return [score_max(modele, extrait(s, t, b)) for s in synthetiseurs for t in textes for b in (False, True)]

    pos, seul, neg = campagne(POSITIFS), campagne(SEUL), campagne(NEGATIFS)
    # Contrôle : le modèle a été entraîné sur de l'anglais. Avec des voix anglaises, il doit
    # détecter ; sinon c'est la chaîne de mesure qui est en cause, pas la prononciation.
    controle = []
    for synth in synthetiseurs:
        if synth.voix.moteur == "kokoro":
            for voix_en in ("am_adam", "bm_george"):
                for texte in ("Hey Jarvis!", "Jarvis!"):
                    son, taux = synth.synthetiser(texte, voix=voix_en, langue="en-us")
                    son = np.concatenate([audio.silence(1.0), audio.reechantillonner(son, taux), audio.silence(1.0)])
                    controle.append(score_max(modele, son))
            break
    resultat = {
        "modele": "openWakeWord hey_jarvis v0.1 (provisoire)",
        "seuil": SEUIL,
        "cpu": cout_cpu(modele),
        "synthese_hey_jarvis_detectes": f"{sum(s >= SEUIL for s in pos)}/{len(pos)}",
        "synthese_jarvis_seul_detectes": f"{sum(s >= SEUIL for s in seul)}/{len(seul)}",
        "synthese_faux_declenchements": f"{sum(s >= SEUIL for s in neg)}/{len(neg)}",
        "score_max_faux": max(neg, default=0.0),
        "scores": {"hey_jarvis": pos, "jarvis_seul": seul, "negatifs": neg},
    }
    if controle:
        resultat["controle_voix_anglaises_detectes"] = f"{sum(s >= SEUIL for s in controle)}/{len(controle)}"
    micro = []
    for e in enregistrements:
        son, taux = audio.lire_wav(Path(e["chemin"]))
        micro.append({"id": e["id"], "attendu": e["attendu"],
                      "score": score_max(modele, audio.reechantillonner(son, taux))})
    if micro:
        resultat["micro"] = micro
    return resultat
