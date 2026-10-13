"""Lot J5 : API, appairage, jetons, WebSocket, confirmations, mémoire."""

import pytest

pytest.importorskip("fastapi")
from aides import LLMScripte
from fastapi.testclient import TestClient

from jarvis.application import Jarvis
from jarvis.config import Config
from jarvis.memoire.stockage import Memoire
from jarvis.memoire.vecteurs import PlongeurHachage
from jarvis.serveur.api import creer_app


@pytest.fixture
def jarvis(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DONNEES", str(tmp_path))
    config = Config()
    config.llm.url_externe = "http://127.0.0.1:9"
    config.jeu.detection = False
    j = Jarvis(config, avec_voix=False, avec_modeles=False)
    j.memoire = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())
    j.orchestrateur.memoire = j.memoire
    j.orchestrateur.llm = LLMScripte(["Bonjour Mathieu, tout va bien."])
    j.orchestrateur.llm_rapide = j.orchestrateur.llm
    j.config.llm.souvenirs_automatiques = False
    return j


def entete(jeton):
    return {"Authorization": f"Bearer {jeton}"}


def test_sans_jeton_refuse(jarvis):
    client = TestClient(creer_app(jarvis))
    assert client.get("/api/journal").status_code == 401
    assert client.get("/api/journal", headers=entete("faux")).status_code == 401


def test_appairage_et_revocation(jarvis):
    client = TestClient(creer_app(jarvis))
    local = entete(jarvis.appareils.jeton_local)
    code = client.post("/api/appareils/code", headers=local).json()["code"]
    assert client.post("/api/appairer", json={"code": "000000" if code != "000000" else "111111", "nom": "x"}).status_code == 403
    r = client.post("/api/appairer", json={"code": code, "nom": "Téléphone"})
    assert r.status_code == 200
    jeton = r.json()["jeton"]
    assert client.post("/api/appairer", json={"code": code, "nom": "bis"}).status_code == 403  # usage unique
    assert client.get("/api/journal", headers=entete(jeton)).status_code == 200
    # Un téléphone ne peut pas générer de code
    assert client.post("/api/appareils/code", headers=entete(jeton)).status_code == 403
    ident = jeton.split(".")[0]
    assert client.delete(f"/api/appareils/{ident}", headers=local).status_code == 200
    assert client.get("/api/journal", headers=entete(jeton)).status_code == 401  # SEC-13


def test_code_limite_en_essais(jarvis):
    code = jarvis.appareils.nouveau_code()
    faux = "123456" if code != "123456" else "654321"
    for _ in range(5):
        assert jarvis.appareils.appairer(faux, "x") is None
    assert jarvis.appareils.appairer(code, "x") is None  # code grillé après 5 essais


def test_message_et_historique(jarvis):
    client = TestClient(creer_app(jarvis))
    h = entete(jarvis.appareils.jeton_local)
    r = client.post("/api/message", json={"texte": "salut"}, headers=h)
    assert r.json()["reponse"].startswith("Bonjour Mathieu")
    assert client.get("/api/historique", headers=h).json()["echanges"][0]["demande"] == "salut"


def test_websocket_discussion_et_evenements(jarvis):
    client = TestClient(creer_app(jarvis))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"jeton": jarvis.appareils.jeton_local})
        assert ws.receive_json()["type"] == "bienvenue"
        ws.send_json({"type": "texte", "texte": "salut"})
        recus = []
        while True:
            m = ws.receive_json()
            recus.append(m)
            if m["type"] == "fin":
                break
        texte = "".join(m["donnees"]["texte"] for m in recus if m["type"] == "morceau")
        assert "Bonjour Mathieu" in texte


def test_websocket_refuse_sans_jeton(jarvis):
    client = TestClient(creer_app(jarvis))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"jeton": "faux"})
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_memoire_consultable_corrigeable_oubliable(jarvis):
    client = TestClient(creer_app(jarvis))
    h = entete(jarvis.appareils.jeton_local)
    ident = jarvis.memoire.memoriser("Mathieu aime le café serré")["id"]
    faits = client.get("/api/memoire", headers=h).json()["faits"]
    assert faits[0]["texte"] == "Mathieu aime le café serré"
    assert client.put(f"/api/memoire/{ident}", json={"texte": "Mathieu aime le thé"}, headers=h).status_code == 200
    assert client.delete(f"/api/memoire/{ident}", headers=h).status_code == 200
    assert client.get("/api/memoire", headers=h).json()["faits"] == []
    assert jarvis.journal.dernieres(1)[0]["outil"] == "oublier"


def test_confirmation_telephone_exige_biometrie(jarvis):
    client = TestClient(creer_app(jarvis))
    jarvis.appareils.nouveau_code()
    code = jarvis.appareils._code[0]
    jeton = jarvis.appareils.appairer(code, "POCO", "android")
    r = client.post("/api/confirmation/1", json={"oui": True}, headers=entete(jeton))
    assert r.status_code == 403  # SEC-12


def test_entetes_de_securite(jarvis):
    client = TestClient(creer_app(jarvis))
    r = client.get("/api/journal", headers=entete(jarvis.appareils.jeton_local))
    assert r.headers["X-Frame-Options"] == "DENY"
