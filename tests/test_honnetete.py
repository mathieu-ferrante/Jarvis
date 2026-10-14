"""Essai réel du 14/10 : rappel annoncé sans être créé, « Retiens que… » mal compris par le modèle.

Corrigé par les commandes rapides (rappels, souvenirs) et la garde d'honnêteté de l'orchestrateur.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from aides import orchestrateur
from test_coeur import Factice

from jarvis.agent.commandes_rapides import a_la_troisieme_personne, reconnaitre
from jarvis.agent.orchestrateur import RELANCE_HONNETETE, action_inventee
from jarvis.outils.base import Niveau

MAINTENANT = datetime(2026, 10, 14, 15, 0)


def test_rappels_reconnus_sans_le_modele():
    c = reconnaitre("Rappelle-moi de sortir le linge dans 10 minutes", maintenant=MAINTENANT)
    assert c.outil == "creer_rappel" and c.args == {"texte": "Sortir le linge", "quand": "2026-10-14T15:10:00"}
    c = reconnaitre("Jarvis, rappelle-moi d'appeler Paul et Marie à 18h30", maintenant=MAINTENANT)
    assert c.args == {"texte": "Appeler Paul et Marie", "quand": "2026-10-14T18:30:00"}
    c = reconnaitre("rappelle moi demain à 9 h de payer le loyer", maintenant=MAINTENANT)
    assert c.args["quand"] == "2026-10-15T09:00:00" and c.args["texte"] == "Payer le loyer"
    # « à 8 h » dit à 15 h : ce soir ; « à 14 h » dit à 15 h : demain
    assert reconnaitre("rappelle-moi de manger à 8h", maintenant=MAINTENANT).args["quand"] == "2026-10-14T20:00:00"
    assert reconnaitre("rappelle-moi de partir à 14h", maintenant=MAINTENANT).args["quand"] == "2026-10-15T14:00:00"
    assert reconnaitre("rappelle-moi de X dans une heure", maintenant=MAINTENANT).args["quand"] == "2026-10-14T16:00:00"
    # Ambigu ou composé : au modèle
    assert reconnaitre("rappelle-moi de X dans 10 minutes et lance Spotify", maintenant=MAINTENANT) is None
    assert reconnaitre("Rappelle-moi ce que j'ai dit hier", maintenant=MAINTENANT) is None
    assert reconnaitre("rappelle-moi de X à 25h", maintenant=MAINTENANT) is None


def test_retiens_que():
    c = reconnaitre("Retiens que je joue à CS2 surtout en deathmatch.")
    assert c.outil == "memoriser" and c.args == {"fait": "Mathieu joue à CS2 surtout en deathmatch"}
    assert reconnaitre("retiens que je suis allergique aux noix").args["fait"] == "Mathieu est allergique aux noix"
    assert reconnaitre("Retiens que le code du portail est 1234").args["fait"] == "Le code du portail est 1234"
    assert reconnaitre("retiens que quoi ?") is None


def test_troisieme_personne_ou_citation_fidele():
    assert a_la_troisieme_personne("j'ai un chat qui s'appelle Pixel") == "Mathieu a un chat qui s'appelle Pixel"
    assert a_la_troisieme_personne("je joue avec mon frère") == "Mathieu joue avec son frère"
    assert a_la_troisieme_personne("je finis à 18 h") == "Mathieu finit à 18 h"
    # Conjugaison incertaine : on cite plutôt que d'écrire faux
    assert a_la_troisieme_personne("je me lève à 7 h") == "Mathieu a dit : « je me lève à 7 h »"
    assert a_la_troisieme_personne("mon frère s'appelle Léo") == "Mathieu a dit : « mon frère s'appelle Léo »"
    assert a_la_troisieme_personne("je cours le dimanche").startswith("Mathieu a dit")


def test_detection_d_action_inventee():
    assert action_inventee("Rappelle-moi de sortir le linge", "Je vais vous rappeler de sortir le linge.", [])
    assert action_inventee("Jarvis, envoie le mail", "C'est fait !", [])
    assert not action_inventee("Rappelle-moi de sortir le linge", "Je vais vous rappeler.", [{"ok": True}])
    assert not action_inventee("Combien font 17 fois 23 ?", "C'est fait : 391.", [])  # pas une demande d'action
    assert not action_inventee("Lance Spotify", "Je ne peux pas, Spotify n'est pas installé.", [])


def test_relance_puis_action_reelle(tmp_path):
    outil = Factice("regler_x", Niveau.REVERSIBLE, verif=True)
    o = orchestrateur(tmp_path, ["C'est fait.", [("regler_x", {"x": 3})], "Réglé sur 3."], [outil])
    reponse = asyncio.run(o.repondre_texte("Règle x sur 3", canal="texte"))
    assert outil.appels == [3] and "Correction" not in reponse and "Réglé sur 3" in reponse
    assert any(m.get("content") == RELANCE_HONNETETE for m in o.llm.recus[1])
    assert all(m.get("content") != RELANCE_HONNETETE for m in o.conversations["principale"])


def test_relance_sans_effet_donc_correction(tmp_path):
    outil = Factice("regler_x", Niveau.REVERSIBLE)
    o = orchestrateur(tmp_path, ["C'est fait.", "C'est fait, vraiment."], [outil])
    reponse = asyncio.run(o.repondre_texte("Règle x sur 3", canal="texte"))
    assert outil.appels == [] and reponse.endswith("Correction : je ne l'ai pas fait.")
    assert len(o.llm.recus) == 2  # une seule relance


def test_creer_dossier_un_seul_niveau(tmp_path):
    from jarvis.outils.base import Contexte
    from jarvis.outils.fichiers import CreerDossier

    ctx = Contexte()
    r = asyncio.run(CreerDossier().executer(ctx, chemin=str(tmp_path / "Projets")))
    assert r.ok and (tmp_path / "Projets").is_dir()
    # Chemin inventé (le 14/10 : « C:\Users\…\prett\Essai ») : rien n'est créé
    r = asyncio.run(CreerDossier().executer(ctx, chemin=str(tmp_path / "prett" / "Essai")))
    assert not r.ok and "parent" in r.message and not (tmp_path / "prett").exists()


def test_bureau_reel_de_windows(monkeypatch):
    from jarvis.outils import fichiers

    monkeypatch.setattr(fichiers, "dossier_connu", lambda nom: Path(r"C:\Users\m\OneDrive\Bureau") if nom == "Desktop"
                        else Path(r"C:\Users\m") / nom)
    assert fichiers.resoudre("Bureau/Essai") == Path(r"C:\Users\m\OneDrive\Bureau\Essai")
    assert fichiers.resoudre("téléchargements") == Path(r"C:\Users\m\Downloads")
    assert fichiers.dossier_connu("Desktop").name == "Bureau"
