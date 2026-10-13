"""Réflexion à la demande et souvenirs automatiques."""

import asyncio

from aides import LLMScripte, orchestrateur

from jarvis.agent import routeur
from jarvis.memoire import extraction
from jarvis.memoire.stockage import Memoire
from jarvis.memoire.vecteurs import PlongeurHachage


def test_besoin_reflexion():
    assert not routeur.besoin_reflexion("baisse le son")
    assert routeur.besoin_reflexion("explique-moi pourquoi mon aim est moins bon en fin de session")
    assert routeur.besoin_reflexion("prépare-moi un plan d'entraînement pour progresser en Premier")
    assert not routeur.besoin_reflexion("quelle heure est-il")
    assert not routeur.besoin_reflexion("explique la planète Mars", mode="jamais")
    assert routeur.besoin_reflexion("salut", mode="toujours")


def test_reflexion_activee_et_annoncee_a_l_oral(tmp_path):
    o = orchestrateur(tmp_path, ["Voici mon analyse."], [])
    reponse = asyncio.run(o.repondre_texte("analyse ma dernière semaine de jeu", canal="voix"))
    assert reponse.startswith("Laisse-moi réfléchir.")
    assert o.llm.reflexions == [True]
    o2 = orchestrateur(tmp_path, ["C'est fait."], [])
    asyncio.run(o2.repondre_texte("baisse le son", canal="voix"))
    assert o2.llm.reflexions == [False]


def test_pas_de_reflexion_en_jeu(tmp_path):
    o = orchestrateur(tmp_path, ["Bref."], [], en_jeu=lambda: True)
    asyncio.run(o.repondre_texte("analyse ma partie", canal="voix"))
    assert o.llm.reflexions == [False]


def test_lire_faits():
    assert extraction.lire_faits('Voici : ["Mathieu joue en Premier", "Le ciel est bleu"]') == ["Mathieu joue en Premier"]
    assert extraction.lire_faits("rien") == []
    assert extraction.lire_faits("[]") == []


def test_merite_extraction():
    assert extraction.merite_extraction("je préfère jouer le soir après le travail")
    assert not extraction.merite_extraction("baisse le son")


def test_souvenirs_automatiques(tmp_path):
    memoire = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())
    o = orchestrateur(tmp_path, ["Noté, bon courage pour ton entraînement !"], [], memoire=memoire)
    o.llm.par_mot_cle["Mathieu : "] = ['["Mathieu s\'entraîne au deathmatch tous les soirs"]']

    async def scenario():
        await o.repondre_texte("je fais du deathmatch tous les soirs avant de jouer en Premier", canal="voix")
        await asyncio.gather(*o._taches_fond)

    asyncio.run(scenario())
    faits = memoire.lister()
    assert len(faits) == 1 and faits[0]["source"] == "déduit de la conversation"
    assert any(e.type == "souvenir" for e in o.bus.historique)


def test_pas_de_souvenir_depuis_un_contenu_lu(tmp_path):
    memoire = Memoire(tmp_path / "m.sqlite", plongeur=PlongeurHachage())
    llm = LLMScripte([])
    asyncio.run(extraction.extraire_et_retenir(llm, memoire, "baisse le son", "ok"))
    assert memoire.lister() == [] and llm.recus == []  # filtre : pas même sollicité
