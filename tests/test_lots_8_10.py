"""Lots J8 (initiative), J9 (mode jeu, Postgame, projets) et J10 (maison connectée)."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from jarvis.config import Config
from jarvis.evenements import Bus
from jarvis.llm.client import Reponse
from jarvis.memoire.stockage import Memoire
from jarvis.memoire.vecteurs import PlongeurHachage
from jarvis.outils import dev, maison, postgame
from jarvis.outils.base import Contexte
from jarvis.rappels import ServiceRappels
from jarvis.securite.journal import Journal


@pytest.fixture(autouse=True)
def donnees(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DONNEES", str(tmp_path))


class FauxLLM:
    def __init__(self, texte):
        self.texte = texte

    async def discuter(self, messages, outils=None, max_tokens=1024, reflexion=False):
        return Reponse(texte=self.texte)


class FauxJarvis:
    def __init__(self, tmp_path, llm_texte="RIEN"):
        self.config = Config()
        self.bus = Bus()
        self.etat_jeu = {"en_jeu": False, "jeu": None}
        self.memoire = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())
        self.rappels = ServiceRappels(tmp_path / "r.sqlite")
        self.journal = Journal(tmp_path / "j.sqlite")
        self.llm = FauxLLM(llm_texte)
        self.coffre = None
        self.avec_modeles = False
        self.metriques = type("M", (), {"pret": True})()


# --- J8 : initiative ------------------------------------------------------------------------


def test_briefing_a_la_premiere_activite_du_jour(tmp_path):
    from jarvis.initiative import Initiative

    i = Initiative(FauxJarvis(tmp_path))
    matin = datetime(2026, 10, 14, 7, 30)
    assert not i.doit_briefer(matin, inactivite_s=6 * 3600)  # personne au PC
    assert i.doit_briefer(matin, inactivite_s=5)  # première activité après la nuit
    i.etat["dernier_briefing"] = "2026-10-14"
    assert not i.doit_briefer(matin, inactivite_s=5)  # une seule fois par jour
    assert not i.doit_briefer(datetime(2026, 10, 15, 3, 0), inactivite_s=5)  # trop tôt
    i.jarvis.etat_jeu["en_jeu"] = True
    assert not i.doit_briefer(datetime(2026, 10, 15, 8, 0), inactivite_s=5)  # pas en jeu


def test_suggestions_limitees_et_journalisees(tmp_path):
    from jarvis.initiative import SUGGESTIONS_PAR_JOUR, Initiative

    j = FauxJarvis(tmp_path, "Tu m'avais demandé de penser à l'anniversaire de Léa demain.")
    j.memoire.memoriser("L'anniversaire de Léa est le 15 octobre")
    i = Initiative(j)
    resultats = [asyncio.run(i.suggestion()) for _ in range(5)]
    assert sum(r is not None for r in resultats) == SUGGESTIONS_PAR_JOUR["discret"]
    assert j.journal.dernieres(1)[0]["outil"] == "suggestion"
    j.config.initiative.suggestions = False
    i.etat["suggestions"] = {}
    assert asyncio.run(i.suggestion()) is None  # niveau silencieux


def test_annonces_retenues_redites_apres_la_partie(tmp_path):
    from jarvis.initiative import Initiative

    j = FauxJarvis(tmp_path)
    Initiative(j)
    j.bus.publier("voix_annonce_retenue", texte="Tâche terminée : tri des photos")
    j.bus.publier("jeu", etat="inactif")
    notif = [e for e in j.bus.historique if e.type == "notification"]
    assert notif and "tri des photos" in notif[0].donnees["texte"]


# --- J9 : mode jeu --------------------------------------------------------------------------


def test_bascule_mode_jeu(tmp_path, monkeypatch):
    from jarvis import jeu

    j = FauxJarvis(tmp_path)
    reglages = []
    monkeypatch.setattr(jeu, "regler_processus", lambda pid, en_jeu: reglages.append(en_jeu))
    d = jeu.DetecteurJeu(j)
    monkeypatch.setattr(d, "jeu_en_cours", lambda: "cs2.exe")
    asyncio.run(d.entrer("cs2.exe"))
    assert j.etat_jeu == {"en_jeu": True, "jeu": "cs2.exe"} and reglages == [True]
    assert any(e.type == "jeu" and e.donnees.get("etat") == "actif" for e in j.bus.historique)
    asyncio.run(d.sortir())
    assert j.etat_jeu["en_jeu"] is False and reglages == [True, False]


def test_coeurs_reserves():
    from jarvis.jeu import coeurs_reserves

    coeurs = coeurs_reserves(4)
    assert len(coeurs) == 4 and coeurs == sorted(coeurs)


# --- J9 : Postgame --------------------------------------------------------------------------


PARTIES = [
    {"id": 3, "jeu": "cs2", "date_partie": "2026-10-13T21:40:00", "mode": "Deathmatch", "carte": "de_mirage", "resultat": None},
    {"id": 2, "jeu": "cs2", "date_partie": "2026-10-13T21:20:00", "mode": "Deathmatch", "carte": "de_dust2", "resultat": None},
    {"id": 1, "jeu": "cs2", "date_partie": "2026-10-12T20:00:00", "mode": "Deathmatch", "carte": "de_inferno", "resultat": None},
]


def faux_postgame(monkeypatch, appels):
    class Rep:
        def __init__(self, d, code=200):
            self.d, self.status_code = d, code

        def json(self):
            return self.d

        def raise_for_status(self):
            pass

    async def faux_http(self, methode, url, hotes=None, params=None, headers=None):
        appels.append(url)
        assert hotes == ("127.0.0.1",)
        if url.endswith("/api/parties"):
            return Rep({"total": 3, "parties": PARTIES[: params.get("limite", 50)]})
        ident = int(url.rsplit("/", 1)[1])
        return Rep({"id": ident, "mesures": [{"nom": "kills_par_minute", "valeur": 2.0 + ident / 10},
                                            {"nom": "precision_tete_pct", "valeur": 30 + ident}]})

    monkeypatch.setattr(Contexte, "http", faux_http)


def test_derniere_session_postgame(monkeypatch):
    appels = []
    faux_postgame(monkeypatch, appels)
    outil = postgame.StatistiquesJeu()
    r = asyncio.run(outil.executer(Contexte(config=Config(), outil=outil), jeu="cs2", mode="DM"))
    assert r.ok and len(r.donnees["parties"]) == 2  # la partie de la veille n'est pas dans la session
    assert r.donnees["parties"][0]["mesures"]["precision_tete_pct"] == 33
    assert all("debrief" not in u for u in appels)


def test_debrief_rédigé_localement_sans_appeler_postgame_debrief(monkeypatch):
    appels = []
    faux_postgame(monkeypatch, appels)
    outil = postgame.DebriefPartie()
    r = asyncio.run(outil.executer(Contexte(config=Config(), outil=outil), jeu="cs2"))
    assert r.ok and "kills_par_minute" in r.message
    assert appels[-1].endswith("/api/parties/3") and all("debrief" not in u for u in appels)


def test_debrief_postgame_interdit():
    client = postgame.ClientPostgame(Contexte(config=Config()))
    with pytest.raises(PermissionError):
        asyncio.run(client.get("/api/parties/3/debrief"))


def test_tendance():
    fiches = [{"mesures": [{"nom": "precision", "valeur": v}]} for v in (40, 38, 30, 28)]
    assert postgame.tendance(fiches) == {"precision": {"recent": 39.0, "avant": 29.0}}


def test_postgame_injoignable(monkeypatch):
    async def faux_http(self, *a, **k):
        raise ConnectionError("refusé")

    monkeypatch.setattr(Contexte, "http", faux_http)
    r = asyncio.run(postgame.StatistiquesJeu().executer(Contexte(config=Config()), jeu="lol"))
    assert not r.ok and "injoignable" in r.message


# --- J9 : projets perso ---------------------------------------------------------------------


def test_etat_du_depot_jarvis():
    racine = Path(__file__).resolve().parents[1]
    config = Config()
    config.integrations.depots = [str(racine)]
    ctx = Contexte(config=config)
    r = asyncio.run(dev.EtatDepot().executer(ctx, projet="jarvis"))
    assert r.ok and "branche" in r.message and "Derniers commits" in r.message
    assert dev.commande_de_tests(racine)[-3:] == ["pytest", "-q", "--no-header"]
    assert asyncio.run(dev.ResumerChangements().executer(ctx, projet="jarvis", depuis="10 years ago")).ok


# --- J10 : maison ---------------------------------------------------------------------------

ETATS = [
    {"entity_id": "light.salon", "state": "off", "attributes": {"friendly_name": "Lumière du salon"}},
    {"entity_id": "lock.entree", "state": "locked", "attributes": {"friendly_name": "Serrure de l'entrée"}},
    {"entity_id": "cover.garage", "state": "closed", "attributes": {"friendly_name": "Porte du garage", "device_class": "garage"}},
    {"entity_id": "sensor.temp_salon", "state": "21.5", "attributes": {"friendly_name": "Température salon", "unit_of_measurement": "°C"}},
]


class Coffre:
    def lire(self, nom):
        return "jeton-ha"


@pytest.fixture
def ctx_maison(monkeypatch):
    appels = []

    class Rep:
        status_code = 200

        def __init__(self, d):
            self.d = d

        def json(self):
            return self.d

        def raise_for_status(self):
            pass

    async def faux_http(self, methode, url, hotes=None, headers=None, json=None):
        assert hotes == ("homeassistant.local",) and headers["Authorization"] == "Bearer jeton-ha"
        if methode == "POST":
            appels.append((url.split("/api/services/")[1], json))
            return Rep([])
        return Rep(ETATS)

    monkeypatch.setattr(Contexte, "http", faux_http)
    config = Config()
    config.integrations.home_assistant_url = "http://homeassistant.local:8123"
    return Contexte(config=config, coffre=Coffre()), appels


def test_commander_lumiere(ctx_maison):
    ctx, appels = ctx_maison
    r = asyncio.run(maison.CommanderMaison().executer(ctx, appareil="lumière salon", action="regler", valeur=40))
    assert r.ok and appels == [("light/turn_on", {"entity_id": "light.salon", "brightness_pct": 40})]


def test_securite_separee(ctx_maison):
    ctx, appels = ctx_maison
    assert not asyncio.run(maison.CommanderMaison().executer(ctx, appareil="serrure entrée", action="ouvrir")).ok
    assert not asyncio.run(maison.CommanderMaison().executer(ctx, appareil="porte du garage", action="ouvrir")).ok
    assert appels == []
    r = asyncio.run(maison.CommanderSecuriteMaison().executer(ctx, appareil="serrure entrée", action="ouvrir"))
    assert r.ok and appels == [("lock/unlock", {"entity_id": "lock.entree"})]
    assert maison.CommanderSecuriteMaison.niveau.nom_fr == "irreversible"


def test_etat_maison(ctx_maison):
    ctx, _ = ctx_maison
    r = asyncio.run(maison.EtatMaison().executer(ctx, appareil="température salon"))
    assert r.ok and "21.5 °C" in r.message


def test_maison_non_configuree():
    with pytest.raises(RuntimeError, match="non configuré"):
        asyncio.run(maison.EtatMaison().executer(Contexte(config=Config(), coffre=Coffre())))
