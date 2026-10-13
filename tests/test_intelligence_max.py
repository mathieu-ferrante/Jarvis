"""Lot J17 : habitudes et propositions, personnalisation, agent écran, batterie de 200 commandes."""

import asyncio
import json
from datetime import datetime, timedelta

from jarvis.agent import personnalisation
from jarvis.banc import charger_batterie
from jarvis.config import Config
from jarvis.habitudes import detecter
from jarvis.llm.client import Reponse
from jarvis.memoire import extraction
from jarvis.memoire.stockage import Memoire
from jarvis.memoire.vecteurs import PlongeurHachage
from jarvis.outils import agent_ecran
from jarvis.outils.base import Contexte
from jarvis.outils.registre import Registre


def action(jours: int, heure: str, outil="lancer_application", args=None, ok=True, origine="voix"):
    quand = datetime(2026, 10, 13) - timedelta(days=jours)
    h, m = map(int, heure.split(":"))
    return {"horodatage": quand.replace(hour=h, minute=m).isoformat(), "outil": outil,
            "arguments": json.dumps(args or {"nom": "Spotify"}), "ok": ok, "origine": origine, "demande": "lance Spotify"}


def test_detection_d_habitude():
    actions = [action(1, "21:05"), action(2, "20:50"), action(4, "21:20"), action(5, "09:00", args={"nom": "Excel"})]
    h = detecter(actions, datetime(2026, 10, 13, 12))
    assert len(h) == 1 and h[0]["jours"] == 3 and "lance spotify vers 21 h" in h[0]["texte"].lower()
    # Heures trop dispersées : pas une habitude
    assert detecter([action(1, "08:00"), action(2, "14:00"), action(3, "22:00")], datetime(2026, 10, 13, 12)) == []
    # Autour de minuit (moyenne circulaire)
    assert detecter([action(1, "23:50"), action(2, "00:10"), action(3, "23:55")], datetime(2026, 10, 13, 12))


def test_propositions_acceptees_refusees_sans_insister(tmp_path):
    m = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())
    a = m.proposer("Mathieu joue souvent le soir après 21 h")
    b = m.proposer("Mathieu boit du thé le matin")
    assert m.proposer("Mathieu joue souvent le soir après 21 h.") is None  # déjà proposé
    assert m.decider_proposition(a, True)["id"]
    assert "21 h" in m.lister()[0]["texte"] and "accepté" in m.lister()[0]["source"]
    assert m.decider_proposition(b, False) == {"refusee": True}
    assert m.proposer("Mathieu boit du thé le matin") is None  # refusé : jamais reproposé
    assert m.propositions() == [] and len(m.lister()) == 1


def test_extraction_propose_au_lieu_de_retenir(tmp_path):
    m = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())

    class LLM:
        async def discuter(self, *a, **k):
            return Reponse(texte='["Mathieu s\'entraîne au deathmatch tous les soirs"]')

    asyncio.run(extraction.extraire_et_retenir(LLM(), m, "je fais du deathmatch tous les soirs", "ok"))
    assert m.lister() == [] and len(m.propositions()) == 1


def test_personnalisation_par_exemples():
    actions = [action(0, "10:00", outil=o, args={"x": i}) | {"demande": f"demande {i}"}
               for i, o in enumerate(["regler_volume", "jouer_musique", "regler_volume", "meteo", "creer_rappel"])]
    actions.append(action(0, "10:00", outil="envoyer_mail") | {"origine": "tache"})  # pas une demande directe
    bloc = personnalisation.bloc_consignes(actions)
    assert bloc.count("→") == 4 and "envoyer_mail" not in bloc  # un exemple par outil
    assert personnalisation.bloc_consignes(actions[:2]) == ""  # trop peu d'exemples


def test_agent_ecran_boucle_jusqu_a_fini(monkeypatch):
    faites = []
    monkeypatch.setattr("jarvis.outils.vision.capturer", lambda *a: b"png")
    monkeypatch.setattr("jarvis.outils.windows.ecran_principal", lambda: (1920, 1080))
    monkeypatch.setattr(agent_ecran, "executer_action", lambda a, l, h: faites.append(a["action"]) or a["action"])
    reponses = iter(['{"action": "cliquer", "x": 500, "y": 500, "explication": "ouvre le menu"}',
                     'Voilà : {"action": "fini", "explication": "option cochée"}'])

    class LLM:
        async def discuter(self, messages, **k):
            assert messages[1]["content"][1]["type"] == "image_url"
            return Reponse(texte=next(reponses))

    monkeypatch.setattr(asyncio, "sleep", _sans_attente)
    ctx = Contexte(config=Config(), services={"llm": LLM()})
    r = asyncio.run(agent_ecran.PiloterEcran().executer(ctx, objectif="cocher l'option"))
    assert r.ok and faites == ["cliquer"] and "option cochée" in r.message


async def _sans_attente(*a, **k):
    return None


def test_agent_ecran_conversions():
    assert agent_ecran.vers_pixels(500, 500, 1920, 1080) == (960, 540)
    assert agent_ecran.vers_pixels(2000, -5, 1920, 1080) == (1919, 0)
    assert agent_ecran.lire_action("rien") is None
    assert agent_ecran.lire_action('{"action": "ecrire", "texte": "bonjour"}')["texte"] == "bonjour"
    assert agent_ecran.PiloterEcran.niveau.nom_fr == "irreversible"


def test_batterie_de_200_commandes():
    bat = charger_batterie()
    registre = Registre().charger_tout()
    ids = [c["id"] for c in bat["cas"]]
    assert len(ids) >= 200 and len(ids) == len(set(ids))
    for c in bat["cas"]:
        for a in c["attendu"]:
            assert a["outil"] in registre, (c["id"], a["outil"])
        for i in c.get("interdits", []):
            assert i in registre, (c["id"], i)
