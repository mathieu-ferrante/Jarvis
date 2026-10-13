"""Chemin rapide (PERF-02) et garde anti-boucle."""

import asyncio

from aides import orchestrateur

from jarvis.agent.commandes_rapides import lire_nombre, reconnaitre
from jarvis.outils.base import Niveau, Outil, Resultat


def test_nombres():
    assert lire_nombre("30") == 30
    assert lire_nombre("trente") == 30
    assert lire_nombre("vingt-cinq") == 25
    assert lire_nombre("soixante-dix-huit") == 78
    assert lire_nombre("quatre-vingt-dix") == 90
    assert lire_nombre("bleu") is None


def test_reconnaissance():
    c = reconnaitre("Jarvis, mets le son à trente pour cent.")
    assert (c.outil, c.args) == ("regler_volume", {"niveau": 30})
    assert reconnaitre("baisse un peu le son").args == {"variation": -10}
    assert reconnaitre("monte le volume de 20 %").args == {"variation": 20}
    assert reconnaitre("Chanson suivante.").args == {"action": "suivant"}
    assert reconnaitre("mets en pause s'il te plaît").args == {"action": "pause"}
    m = reconnaitre("Mets un minuteur de cinq minutes pour les pâtes")
    assert m.args == {"duree_secondes": 300, "libelle": "les pates"}
    assert reconnaitre("lance un minuteur d'une demi-heure").args == {"duree_secondes": 1800}
    assert reconnaitre("Quelle heure est-il ?").outil == "date_et_heure"


def test_ambigu_va_au_modele():
    assert reconnaitre("mets le volume à 20 et lance Steam") is None
    assert reconnaitre("explique-moi les minuteurs") is None
    assert reconnaitre("lance Spotify") is None  # application inconnue (pas de vérificateur)
    assert reconnaitre("lance Spotify", application_connue=lambda n: n == "spotify").args == {"nom": "spotify"}
    assert reconnaitre("ouvre le fichier facture", application_connue=lambda n: True) is None
    assert reconnaitre("active le mode jeu", routine_connue=lambda n: False) is None


class Volume(Outil):
    nom = "regler_volume"
    description = "volume"
    parametres = {"type": "object", "properties": {"niveau": {"type": "integer"}, "variation": {"type": "integer"},
                                                   "muet": {"type": "boolean"}}}
    niveau = Niveau.REVERSIBLE

    def __init__(self):
        self.appels = []

    async def executer(self, ctx, **args):
        self.appels.append(args)
        return Resultat(True, "Volume : 50 % → 30 %.")


def test_chemin_rapide_sans_modele_mais_journalise(tmp_path):
    outil = Volume()
    o = orchestrateur(tmp_path, [], [outil])
    reponse = asyncio.run(o.repondre_texte("mets le son à 30", canal="voix"))
    assert reponse == "Volume à 30 %." and outil.appels == [{"niveau": 30}]
    assert o.llm.recus == []  # le modèle n'a pas été sollicité
    assert o.journal.dernieres(1)[0]["outil"] == "regler_volume"


def test_garde_anti_boucle(tmp_path):
    outil = Volume()
    o = orchestrateur(tmp_path, [[("regler_volume", {"niveau": 40})], [("regler_volume", {"niveau": 40})], "Fait."],
                      [outil])
    asyncio.run(o.repondre_texte("règle le son comme hier", canal="texte"))
    assert outil.appels == [{"niveau": 40}]
    assert "déjà été exécuté" in o.llm.recus[-1][-1]["content"]
