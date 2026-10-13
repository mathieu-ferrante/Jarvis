"""Lot J14 : agent macOS (outils, protocole, secours) — commandes système simulées."""

import asyncio
import subprocess

import pytest

from jarvis.mac import agent as module_agent
from jarvis.mac import outils_mac
from jarvis.securite.reseau import GardeReseau, SortieRefusee


class Sortie:
    def __init__(self, stdout="", code=0):
        self.stdout, self.stderr, self.returncode = stdout, "", code


@pytest.fixture
def commandes(monkeypatch):
    lancees = []

    def faux_run(cmd, **kw):
        lancees.append(cmd)
        if cmd[:2] == ["osascript", "-e"] and "output volume of" in cmd[2]:
            return Sortie("30\n")
        if cmd[0] == "mdfind":
            return Sortie("/Users/m/Documents/facture.pdf\n")
        return Sortie("")

    monkeypatch.setattr(subprocess, "run", faux_run)
    return lancees


def test_echappement_applescript():
    assert outils_mac.echapper('a"; do shell script "rm -rf ~"; "') == '"a\\"; do shell script \\"rm -rf ~\\"; \\""'


def test_volume_et_recherche(commandes):
    ok, message = outils_mac.executer("regler_volume", {"niveau": 30})
    assert ok and "30 %" in message and ["osascript", "-e", "set volume output volume 30"] in commandes
    ok, message = outils_mac.executer("chercher_fichiers", {"requete": "facture"})
    assert ok and "facture.pdf" in message


def test_rappel_avec_echeance(commandes):
    from datetime import datetime, timedelta

    quand = (datetime.now() + timedelta(minutes=20)).isoformat(timespec="seconds")
    ok, _ = outils_mac.executer("creer_rappel", {"texte": 'Appeler "Théo"', "quand": quand})
    script = commandes[-1][2]
    assert ok and 'name:"Appeler \\"Théo\\""' in script and "(current date) +" in script


def test_niveaux_alignes_sur_windows():
    niveaux = {d["nom"]: d["niveau"] for d in outils_mac.DEFINITIONS}
    assert niveaux["envoyer_mail"] == "irreversible"
    assert niveaux["chercher_fichiers"] == "lecture" and niveaux["lancer_application"] == "reversible"


def test_garde_reseau_n_autorise_que_le_pc():
    garde = GardeReseau()
    garde.hotes_globaux = ("pc-jeu.tailnet.ts.net",)
    garde._crochet("socket.getaddrinfo", ("pc-jeu.tailnet.ts.net", 443, 0, 0, 0))
    with pytest.raises(SortieRefusee):
        garde._crochet("socket.getaddrinfo", ("api.openai.com", 443, 0, 0, 0))


def test_agent_execute_un_outil_et_rend_le_resultat(commandes, monkeypatch):
    monkeypatch.setattr(module_agent.GARDE, "installer", lambda: None)
    agent = module_agent.AgentMac("https://pc.tailnet.ts.net", "mac1.secret")
    envoyes = []

    async def envoyer(m):
        envoyes.append(m)

    agent.envoyer = envoyer
    asyncio.run(agent._traiter({"type": "bienvenue", "donnees": {}}))
    assert envoyes[0]["type"] == "outils" and len(envoyes[0]["outils"]) == len(outils_mac.DEFINITIONS)
    asyncio.run(agent._traiter({"type": "executer", "donnees": {"id": "x1", "outil": "regler_volume", "args": {"niveau": 30}}}))
    assert envoyes[-1] == {"type": "resultat", "donnees": {"id": "x1", "ok": True, "message": "Volume du Mac : 30 %."}}
    module_agent.GARDE.hotes_globaux = ()


def test_secours_annonce_le_mode_reduit(tmp_path, monkeypatch):
    from aides import LLMScripte

    from jarvis.mac import secours

    s = secours.Secours(journal=tmp_path / "j.sqlite")
    assert "analyser_ecran" not in s.orchestrateur.registre  # la vision exige le PC
    s.orchestrateur.llm = LLMScripte(["Il est 15 h."])

    async def pret():
        return None

    monkeypatch.setattr(s, "_demarrer", pret)
    reponse = asyncio.run(s.repondre("quelle heure est-il"))
    assert reponse.startswith(secours.PREFIXE) and "15 h" in reponse
