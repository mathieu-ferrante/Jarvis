"""Lot J18 : proactivité réglable, habitudes acceptées proposées à l'heure, coach en direct."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from test_lots_8_10 import FauxJarvis

from jarvis.config import Config
from jarvis.outils import postgame
from jarvis.outils.base import Contexte


@pytest.fixture(autouse=True)
def donnees(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DONNEES", str(tmp_path))


def test_niveaux_de_proactivite(tmp_path):
    from jarvis.initiative import Initiative

    j = FauxJarvis(tmp_path, "Pense à l'anniversaire de Léa.")
    j.memoire.memoriser("L'anniversaire de Léa est demain")
    i = Initiative(j)
    i.regler_niveau("silencieux")
    assert asyncio.run(i.suggestion()) is None
    i.regler_niveau("actif")
    assert sum(asyncio.run(i.suggestion()) is not None for _ in range(6)) == 5  # quota du mode actif
    with pytest.raises(ValueError):
        i.regler_niveau("bavard")
    assert j.journal.dernieres(50)[-1]["outil"] == "regler_proactivite"


def test_habitude_acceptee_proposee_a_l_heure(tmp_path):
    from jarvis.initiative import Initiative

    j = FauxJarvis(tmp_path)
    j.orchestrateur = type("O", (), {"conversations": {}})()
    maintenant = datetime(2026, 10, 13, 21, 3)
    for jours in (1, 2, 3):
        quand = (maintenant - timedelta(days=jours)).replace(hour=21, minute=0)
        j.journal._cnx.execute("INSERT INTO actions (horodatage, outil, arguments, niveau, decision, ok, origine) "
                               "VALUES (?,?,?,?,?,?,?)", (quand.isoformat(), "lancer_application",
                                                          json.dumps({"nom": "Spotify"}), "reversible", "annoncee", 1, "voix"))
    j.journal._cnx.commit()
    i = Initiative(j)
    i.regler_niveau("actif")
    assert i.habitude_a_proposer(maintenant) is None  # pas encore acceptée par Mathieu
    from jarvis.habitudes import proposer_habitudes

    ident = proposer_habitudes(j.journal, j.memoire)[0]
    j.memoire.decider_proposition(ident, True)
    h = i.habitude_a_proposer(maintenant)
    assert h is not None
    asyncio.run(i.proposer_habitude(h, maintenant))
    assert "Je le fais ?" in j.orchestrateur.conversations["principale"][-1]["content"]
    assert i.habitude_a_proposer(maintenant) is None  # une seule fois par jour
    assert i.habitude_a_proposer(maintenant.replace(hour=15)) is None


def test_coach_en_direct(monkeypatch):
    class Rep:
        status_code = 200

        def json(self):
            return {"en_partie": True, "or": 1350, "score": "3/1/4", "objets": ["Doran"]}

        def raise_for_status(self):
            pass

    vus = []

    async def faux_http(self, methode, url, hotes=None, params=None, headers=None):
        vus.append(url)
        return Rep()

    monkeypatch.setattr(Contexte, "http", faux_http)
    r = asyncio.run(postgame.CoachEnDirect().executer(Contexte(config=Config()), jeu="lol"))
    assert r.ok and "1350" in r.message and vus == ["http://127.0.0.1:8765/api/lol/live"]
