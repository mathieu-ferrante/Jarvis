"""Lot J16 : mot de réveil personnalisé (réseau + export ONNX), locuteur, annulation d'écho."""

import asyncio

import numpy as np
import onnxruntime as ort

from jarvis.voix import entrainement_reveil as er
from jarvis.voix import locuteur
from jarvis.voix.aec import AnnuleurEcho, FileReference


def test_reseau_apprend_et_s_exporte_en_onnx(tmp_path):
    rng = np.random.default_rng(0)
    X = rng.standard_normal((400, er.FENETRE, 96)).astype(np.float32)
    y = (X[:, -1, 0] > 0).astype(np.float32)  # séparable
    r = er.Reseau()
    pertes = r.entrainer(X, y, epoques=30)
    assert pertes[-1] < pertes[0] / 2
    assert ((r.predire(X) >= 0.5) == (y > 0.5)).mean() > 0.9
    chemin = r.exporter_onnx(tmp_path / "jarvis_perso.onnx")
    session = ort.InferenceSession(str(chemin))
    entree = session.get_inputs()[0]
    assert entree.shape == [1, 16, 96] and session.get_outputs()[0].shape == [1, 1]  # format openWakeWord
    sortie = session.run(None, {entree.name: X[:1]})[0]
    assert abs(float(sortie[0, 0]) - float(r.predire(X[:1])[0])) < 1e-4


def test_augmentation_et_placement():
    rng = np.random.default_rng(0)
    son = np.ones(8000, dtype=np.float32) * 0.5
    place = er.placer_en_fin(son, rng)
    assert len(place) == 32000 and place[-100:].max() == 0 and place[20000:24000].max() > 0
    aug = er.augmenter(place, rng, np.random.default_rng(1).standard_normal(64000).astype(np.float32))
    assert aug.shape == place.shape and aug.dtype == np.float32


class Coffre:
    def __init__(self):
        self.v = {}

    def lire(self, n):
        return self.v.get(n)

    def ecrire(self, n, x):
        self.v[n] = x


class FauxExtracteur:
    def empreinte(self, son):
        return np.array([1.0, 0.0, 0.0]) if son.mean() > 0 else np.array([0.0, 1.0, 0.0])


def test_calibrage_et_verification_du_locuteur():
    rng = np.random.default_rng(0)
    mathieu = [np.array([1.0, 0.1, 0]) + rng.normal(0, 0.05, 3) for _ in range(5)]
    autres = [np.array([0.1, 1.0, 0]) + rng.normal(0, 0.05, 3) for _ in range(5)]
    cal = locuteur.calibrer(mathieu, autres)
    assert 0.2 < cal["seuil"] < cal["min_mathieu"]
    coffre = Coffre()
    v = locuteur.VerificateurLocuteur(coffre, FauxExtracteur())
    assert v.verifier(np.zeros(100))[0]  # non enrôlé : désactivé
    v.enregistrer({"reference": np.array([1.0, 0, 0], dtype=np.float32), "seuil": 0.7})
    v2 = locuteur.VerificateurLocuteur(coffre, FauxExtracteur())  # relu depuis le coffre
    assert v2.verifier(np.full(16000, 0.1, dtype=np.float32))[0]
    assert not v2.verifier(np.full(16000, -0.1, dtype=np.float32))[0]
    assert not v2.verifier(np.full(100, 0.1, dtype=np.float32))[0]  # trop court : refus prudent


def test_annulation_d_echo():
    rng = np.random.default_rng(1)
    n = 1280 * 60
    x = np.convolve(rng.standard_normal(n), np.ones(8) / 8, mode="same").astype(np.float32) * 0.3
    rir = np.zeros(1600)
    rir[640] = 0.6
    rir[700:1600] = rng.standard_normal(900) * np.exp(-np.arange(900) / 150) * 0.1
    d = np.convolve(x, rir)[:n].astype(np.float32)
    e = AnnuleurEcho().traiter(d, x)
    fin = slice(n - 32000, n)
    erle = 10 * np.log10(np.mean(d[fin] ** 2) / np.mean(e[fin] ** 2))
    assert erle > 20


def test_file_reference():
    f = FileReference()
    f.ajouter(np.ones(1000))
    assert f.prendre(600).sum() == 600 and f.prendre(600).sum() == 400 and f.prendre(10).sum() == 0


def test_confirmation_refusee_pour_une_autre_voix():
    from test_voix import CerveauFactice, boucle, son

    from jarvis.voix.audio_es import EntreeSimulee

    class Refuse:
        def verifier(self, s):
            return False, 0.2

    async def scenario():
        entree = EntreeSimulee([son(0.3, False)], temps_reel=True, silence_final_s=3.0)
        b, evts = boucle(entree, CerveauFactice("x"), ["oui"])
        b.verificateur = Refuse()
        tache = asyncio.create_task(b.executer())
        await asyncio.sleep(0.2)

        async def parler():
            await asyncio.sleep(0.3)
            entree.injecter(son(0.8))

        asyncio.create_task(parler())
        reponse = await b.demander_confirmation("Tu confirmes ?", delai_s=5)
        await tache
        return reponse, evts

    reponse, evts = asyncio.run(scenario())
    assert reponse is False and "locuteur_refuse" in [t for t, _ in evts]
