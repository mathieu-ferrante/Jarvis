import hashlib
import io
import re

import pytest

from jarvis import telechargement as t
from jarvis.diagnostic import catalogue


def test_liste_blanche():
    assert t.hote_autorise("https://github.com/ggml-org/llama.cpp/releases/download/x.zip")
    assert t.hote_autorise("https://release-assets.githubusercontent.com/x")
    assert t.hote_autorise("https://huggingface.co/a/b/resolve/c/d")
    assert t.hote_autorise("https://cas-bridge.xethub.hf.co/x")
    assert not t.hote_autorise("https://api.openai.com/v1/chat")
    assert not t.hote_autorise("https://huggingface.co.malveillant.com/x")
    assert not t.hote_autorise("https://evilgithub.com/x")


def test_refus_hote_non_autorise(tmp_path):
    f = t.Fichier("https://exemple.com/modele.bin", "m.bin", 1, "0" * 64)
    with pytest.raises(t.TelechargementRefuse):
        t.telecharger(f, tmp_path)


class _Reponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_verification_empreinte(tmp_path, monkeypatch):
    contenu = b"bonjour jarvis" * 1000
    bon = hashlib.sha256(contenu).hexdigest()
    monkeypatch.setattr(t._ouvreur, "open", lambda req, timeout: _Reponse(contenu))

    f = t.Fichier("https://huggingface.co/x/y", "sous/m.bin", len(contenu), bon)
    chemin = t.telecharger(f, tmp_path)
    assert chemin.read_bytes() == contenu
    # Déjà présent et valide : pas de nouveau téléchargement
    monkeypatch.setattr(t._ouvreur, "open", lambda req, timeout: pytest.fail("téléchargé deux fois"))
    assert t.telecharger(f, tmp_path) == chemin


def test_empreinte_fausse_rejetee(tmp_path, monkeypatch):
    contenu = b"contenu altere"
    monkeypatch.setattr(t._ouvreur, "open", lambda req, timeout: _Reponse(contenu))
    f = t.Fichier("https://huggingface.co/x/y", "m.bin", len(contenu), "f" * 64)
    with pytest.raises(t.TelechargementRefuse):
        t.telecharger(f, tmp_path)
    assert not (tmp_path / "m.bin").exists()


def test_catalogue_coherent():
    tous = catalogue.selection(rapide=False, avec_moe=True, avec_rocm=True).fichiers()
    tous += catalogue.selection(rapide=True).fichiers()
    destinations = {}
    for f in tous:
        assert t.hote_autorise(f.url), f.url
        assert re.fullmatch(r"[0-9a-f]{64}", f.sha256), f"empreinte manquante : {f.nom}"
        assert f.taille > 0
        # Une même destination doit toujours désigner le même fichier
        if f.destination in destinations:
            assert destinations[f.destination] == f.sha256
        destinations[f.destination] = f.sha256


def test_trois_candidats_principaux_au_moins():
    principaux = [m for m in catalogue.MODELES_LLM if m.role == "principal" and not m.optionnel]
    assert len(principaux) >= 3  # BRN-01 : comparatif d'au moins trois modèles
    assert all(m.mmproj for m in principaux), "chaque candidat doit couvrir la vision (BRN-06)"
