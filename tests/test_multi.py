"""Lot J12 : appareils, outils distants, notifications routées, confirmations par appareil, transferts."""

import asyncio
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from jarvis.application import Jarvis
from jarvis.config import Config
from jarvis.memoire.stockage import Memoire
from jarvis.memoire.vecteurs import PlongeurHachage
from jarvis.outils.appareils import trouver_appareil
from jarvis.outils.base import Niveau
from jarvis.securite.permissions import Demande
from jarvis.serveur import multi
from jarvis.serveur.api import creer_app


@pytest.fixture
def jarvis(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DONNEES", str(tmp_path))
    config = Config()
    config.llm.url_externe = "http://127.0.0.1:9"
    config.jeu.detection = False
    config.llm.souvenirs_automatiques = False
    j = Jarvis(config, avec_voix=False, avec_modeles=False)
    j.memoire = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())
    j.orchestrateur.memoire = j.memoire
    return j


def appairer(j, nom, type_="navigateur"):
    j.appareils.nouveau_code()
    return j.appareils.appairer(j.appareils._code[0], nom, type_)


def test_trouver_appareil():
    appareils = [{"id": "a1", "nom": "POCO M7 Pro", "type": "android"}, {"id": "m1", "nom": "MacBook", "type": "mac"}]
    assert trouver_appareil(appareils, "mon téléphone")["id"] == "a1"
    assert trouver_appareil(appareils, "le Mac")["id"] == "m1"
    assert trouver_appareil(appareils, "poco")["id"] == "a1"
    assert trouver_appareil(appareils, "tablette") is None


def test_confirmation_reservee_a_l_appareil_d_origine():
    d = Demande("envoyer_mail", "envoyer un mail", {}, Niveau.IRREVERSIBLE, origine="texte:a1")
    assert d.peut_confirmer("a1") and d.peut_confirmer("pc") and not d.peut_confirmer("m1")
    assert Demande("x", "x", {}, Niveau.IRREVERSIBLE, origine="voix").appareil == "pc"


def test_outil_distant_enregistre_et_execute(jarvis, monkeypatch):
    """Le Mac déclare un outil ; Jarvis l'appelle ; le Mac répond ; l'outil disparaît à la déconnexion."""
    jeton = appairer(jarvis, "MacBook", "mac")
    client = TestClient(creer_app(jarvis))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"jeton": jeton})
        assert ws.receive_json()["type"] == "bienvenue"
        ws.send_json({"type": "outils", "outils": [
            {"nom": "volume_mac", "description": "Règle le volume du Mac", "niveau": "reversible",
             "parametres": {"type": "object", "properties": {"niveau": {"type": "integer"}}}},
            {"nom": "Nom Invalide!", "description": "rejeté"}]})
        reponse = ws.receive_json()
        assert reponse == {"type": "outils_enregistres", "donnees": {"noms": ["macbook_volume_mac"]}}
        outil = jarvis.registre["macbook_volume_mac"]
        assert outil.niveau == Niveau.REVERSIBLE and outil.description.startswith("[MacBook]")
    assert "macbook_volume_mac" not in jarvis.registre


class FauxWS:
    def __init__(self):
        self.envoyes = []

    async def send_text(self, texte):
        self.envoyes.append(json.loads(texte))


def test_execution_distante(jarvis):
    async def scenario():
        ws = FauxWS()
        c = await jarvis.multi.ouvrir({"id": "a1", "nom": "POCO", "type": "android"}, ws)
        jarvis.multi.enregistrer_outils(c, [{"nom": "sonner", "description": "Fait sonner", "niveau": "lecture"}])
        tache = asyncio.create_task(jarvis.registre["poco_sonner"].executer(None))
        await asyncio.sleep(0.01)
        ordre = ws.envoyes[-1]
        assert ordre["type"] == "executer" and ordre["donnees"]["outil"] == "sonner"
        jarvis.multi.resultat_distant({"id": ordre["donnees"]["id"], "ok": True, "message": "Le téléphone sonne."})
        r = await tache
        jarvis.multi.fermer(c)
        return r

    r = asyncio.run(scenario())
    assert r.ok and r.message == "Le téléphone sonne."
    assert "poco_sonner" not in jarvis.registre


def test_routage_des_notifications(jarvis, monkeypatch):
    envoyes = []

    async def faux_envoyer(ident, message):
        envoyes.append((ident, message["donnees"]["texte"]))
        return True

    monkeypatch.setattr(jarvis.multi, "envoyer", faux_envoyer)
    monkeypatch.setattr(multi, "DELAI_RELAIS_S", 0.05)
    jarvis.multi.connexions = {"pc": [object()], "a1": [object()]}
    monkeypatch.setattr(jarvis.multi, "appareil_actif", lambda: "a1")

    async def scenario():
        ident = await jarvis.multi.notifier({"type": "notification", "donnees": {"texte": "Rappel : linge"}})
        lue = await jarvis.multi.notifier({"type": "notification", "donnees": {"texte": "Lue tout de suite"}})
        jarvis.multi.marquer_lu(lue)
        await asyncio.sleep(0.2)
        return ident

    asyncio.run(scenario())
    assert envoyes[0] == ("a1", "Rappel : linge")  # l'appareil actif d'abord
    assert ("pc", "Rappel : linge") in envoyes  # relayée car non lue
    assert ("pc", "Lue tout de suite") not in envoyes  # pas de doublon une fois lue


def test_lien_de_fichier_usage_unique(jarvis, tmp_path):
    f = tmp_path / "photo.txt"
    f.write_text("contenu")
    jeton = appairer(jarvis, "POCO", "android")
    client = TestClient(creer_app(jarvis))
    lien = jarvis.multi.lien_fichier(f)
    h = {"Authorization": f"Bearer {jeton}"}
    assert client.get(lien).status_code == 401  # authentification requise
    assert client.get(lien, headers=h).text == "contenu"
    assert client.get(lien, headers=h).status_code == 404  # usage unique


def test_confirmation_par_un_autre_appareil_refusee(jarvis):
    mac = appairer(jarvis, "MacBook", "mac")
    client = TestClient(creer_app(jarvis))

    async def scenario():
        tache = asyncio.create_task(jarvis.confirmateur.demander(
            Demande("envoyer_mail", "envoyer", {}, Niveau.IRREVERSIBLE, origine="texte:autre")))
        await asyncio.sleep(0.05)
        return tache

    boucle = asyncio.new_event_loop()
    tache = boucle.run_until_complete(scenario())
    ident = max(jarvis.confirmateur.demandes)
    r = client.post(f"/api/confirmation/{ident}", json={"oui": True}, headers={"Authorization": f"Bearer {mac}"})
    assert r.status_code == 403
    tache.cancel()
    boucle.run_until_complete(asyncio.gather(tache, return_exceptions=True))
    boucle.close()
