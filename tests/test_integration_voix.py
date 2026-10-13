"""Boucle vocale de bout en bout avec les vrais moteurs (petit modèle de test, CPU / iGPU).

Lent (chargement des modèles) : lancé avec `pytest -m lent`. Sur le PC de jeu, la même chaîne
avec les modèles choisis mesure NF-01 (voir A_VALIDER.md).
"""

import asyncio

import numpy as np
import pytest

from jarvis import modeles
from jarvis.diagnostic import audio
from jarvis.diagnostic.catalogue import VOIX_TTS
from jarvis.llm.cerveau import CerveauDirect
from jarvis.llm.client import ClientLLM
from jarvis.llm.serveur import Lancement, ServeurModele
from jarvis.voix import moteurs
from jarvis.voix.audio_es import EntreeSimulee, SortieSimulee
from jarvis.voix.boucle import BoucleVocale, ParametresBoucle

pytestmark = pytest.mark.lent


def _present(f) -> bool:
    return modeles.chemin(f).exists()


@pytest.fixture(scope="module")
def moteurs_reels():
    if not all(_present(f) for f in modeles.PARAKEET_ONNX):
        pytest.skip("Parakeet ONNX absent : python -m jarvis installer")
    stt = moteurs.TranscripteurParakeet(4)
    return {"stt": stt, "tts": moteurs.Synthese("piper-siwis"), "vad": moteurs.DetecteurParole(),
            "reveil": moteurs.DetecteurReveil(transcripteur=stt)}


def _phrase(tts, texte: str) -> np.ndarray:
    son, taux = tts.synthetiser(texte)
    return audio.reechantillonner(son, taux)


def test_transcription_parakeet(moteurs_reels):
    son = _phrase(moteurs_reels["tts"], "Rappelle-moi demain matin d'appeler le garage.")
    texte = moteurs_reels["stt"].transcrire(son).lower()
    from jarvis.diagnostic.stt import wer

    # Une voix de synthèse varie d'un rendu à l'autre : on tolère un mot manqué, pas davantage
    assert "garage" in texte and wer("Rappelle-moi demain matin d'appeler le garage.", texte) <= 0.25, texte


def test_reveil_avec_voix_anglaise(moteurs_reels):
    from kokoro_onnx import Kokoro

    kokoro_fichiers = next(v for v in VOIX_TTS if v.cle == "kokoro-ff_siwis").fichiers
    if not all(_present(f) for f in kokoro_fichiers):
        pytest.skip("Kokoro absent")
    k = Kokoro(str(modeles.chemin(kokoro_fichiers[0])), str(modeles.chemin(kokoro_fichiers[1])))
    son, taux = k.create("Hey Jarvis!", voice="am_adam", lang="en-us")
    flux = audio.en_int16(np.concatenate([audio.silence(0.5), audio.reechantillonner(son, taux), audio.silence(0.5)]))
    r = moteurs_reels["reveil"]
    r.reinitialiser()
    assert any(r.traiter(flux[i:i + 1280]) for i in range(0, len(flux) - 1280, 1280))


def test_echange_vocal_complet(moteurs_reels):
    m = modeles.modele_llm("qwen3.5-0.8b")
    if not _present(m.gguf):
        pytest.skip("modèle de test absent")

    async def scenario():
        serveur = ServeurModele()
        await serveur.demarrer(Lancement("qwen3.5-0.8b", "vulkan", 8791, contexte=4096, vision=False))
        client = ClientLLM(serveur.url, temperature=0)
        try:
            question = _phrase(moteurs_reels["tts"], "Quelle est la capitale de la France ?")
            entree = EntreeSimulee([audio.silence(0.3), question], silence_final_s=4.0, temps_reel=True)
            evenements = []
            boucle = BoucleVocale(entree, SortieSimulee(), moteurs_reels["reveil"], moteurs_reels["vad"],
                                  moteurs_reels["stt"], moteurs_reels["tts"], CerveauDirect(client),
                                  ParametresBoucle(ecoute_continue_s=1.0),
                                  sur_evenement=lambda t, d: evenements.append((t, d)))
            boucle.declencher()  # appui pour parler
            await asyncio.wait_for(boucle.executer(), 120)
            return boucle, evenements
        finally:
            await client.fermer()
            await serveur.arreter()

    boucle, evenements = asyncio.run(scenario())
    assert any(t == "transcription" for t, _ in evenements), evenements
    transcription = next(d["texte"] for t, d in evenements if t == "transcription")
    reponse = next(d["texte"] for t, d in evenements if t == "reponse")
    assert "capitale" in transcription.lower()
    assert "paris" in reponse.lower()
    assert boucle.sortie.joue, "aucun son joué"
    latence = boucle.mesures[0].latence_ms
    print(f"\nLatence fin de parole -> premier son (poste de dev) : {latence} ms")
    assert latence is not None
