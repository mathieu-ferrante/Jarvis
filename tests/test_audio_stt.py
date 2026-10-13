import numpy as np

from jarvis.diagnostic import audio, llm, stt


def test_melange_respecte_le_rsb():
    t = np.arange(16000) / 16000
    parole = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    bruit = audio.bruit_pc(16000)
    melange = audio.melanger(parole, bruit, 10)
    residu = melange - parole
    rsb = 10 * np.log10(np.mean(parole**2) / np.mean(residu**2))
    assert abs(rsb - 10) < 0.5


def test_reechantillonnage():
    son = np.zeros(22050, dtype=np.float32)
    assert len(audio.reechantillonner(son, 22050)) == 16000


def test_wav_aller_retour(tmp_path):
    son = (0.5 * np.sin(np.linspace(0, 100, 8000))).astype(np.float32)
    chemin = audio.ecrire_wav(tmp_path / "x.wav", son, 16000)
    relu, taux = audio.lire_wav(chemin)
    assert taux == 16000 and np.allclose(relu, son, atol=1e-3)


def test_normalisation_wer():
    assert stt.normaliser("Jarvis, baisse le son !") == "jarvis baisse le son"
    assert stt.normaliser("Rappelle-moi d'appeler") == "rappelle moi d appeler"
    assert stt.wer("Lance Spotify.", "lance spotify") == 0.0
    assert stt.wer("ferme discord", "ferme le discord") == 0.5


def test_phrases_sans_chiffres():
    phrases = stt.phrases()
    assert len(phrases) >= 5
    assert not any(c.isdigit() for p in phrases for c in p)


def test_extraire_appels():
    reponse = {"choices": [{"message": {"content": None, "tool_calls": [
        {"function": {"name": "regler_volume", "arguments": "{\"niveau\": 30}"}},
        {"function": {"name": "lancer_application", "arguments": "pas du json"}},
    ]}}]}
    appels, texte = llm.extraire_appels(reponse)
    assert appels[0] == {"outil": "regler_volume", "args": {"niveau": 30}}
    assert "_illisible" in appels[1]["args"] and texte == ""


def test_image_test_est_un_png_valide():
    import struct
    import zlib

    png = llm.image_test_png(32, 16)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    largeur, hauteur = struct.unpack(">II", png[16:24])
    assert (largeur, hauteur) == (32, 16)
    debut = png.index(b"IDAT") + 4
    longueur = struct.unpack(">I", png[debut - 8:debut - 4])[0]
    brut = zlib.decompress(png[debut:debut + longueur])
    assert len(brut) == 16 * (1 + 32 * 3)
