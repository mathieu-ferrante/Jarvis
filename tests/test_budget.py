"""Budget de contexte, répétition en boucle, reprise après dépassement (essai réel du 14/10)."""

import asyncio

import httpx
from aides import LLMScripte, orchestrateur
from test_coeur import Factice

from jarvis.agent import budget
from jarvis.llm.client import Evenement, Reponse
from jarvis.outils.base import Niveau


def conversation(n_tours: int, taille: int = 3000) -> list[dict]:
    m = [{"role": "system", "content": "consignes"}]
    for i in range(n_tours):
        m += [{"role": "user", "content": f"question {i}"},
              {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "x"}}]},
              {"role": "tool", "content": "r" * taille},
              {"role": "assistant", "content": "réponse " * 50}]
    m.append({"role": "user", "content": "dernière question"})
    return m


def test_ajuster_retire_les_tours_les_plus_anciens_en_entier():
    m = conversation(6)
    debut = len(m) - 1
    retires = budget.ajuster(m, None, capacite=3000, reserve=1024, debut_tour=debut)
    assert retires % 4 == 0 and retires > 0  # des tours entiers : jamais un résultat d'outil orphelin
    assert len(m) > 2 and m[0]["role"] == "system" and m[1]["role"] == "user"
    assert m[-1]["content"] == "dernière question"
    assert budget.tokens_messages(m) + 1024 <= 3000


def test_ajuster_ne_touche_pas_au_tour_courant():
    m = conversation(0) + [{"role": "tool", "content": "x" * 50_000}]
    assert budget.ajuster(m, None, capacite=1000, reserve=500, debut_tour=1) == 0 and len(m) == 3


def test_tronquer_repetition():
    boucle = "Je ne peux pas envoyer un mail. " * 3
    assert budget.tronquer_repetition(boucle) == "Je ne peux pas envoyer un mail."
    assert budget.tronquer_repetition("Bonjour. Il fait beau. Bonjour.") is None
    assert budget.tronquer_repetition("Je ne peux pas envoyer un mail. Je ne peux pas envoyer un mail. Je ne") is None


def test_outils_de_jeu_seulement_en_partie(tmp_path):
    o = orchestrateur(tmp_path, [], [Factice("meteo", Niveau.LECTURE), Factice("envoyer_mail", Niveau.IRREVERSIBLE)])
    assert {s["function"]["name"] for s in o.schemas_actifs()} == {"meteo", "envoyer_mail"}
    assert o.capacite_contexte() == 16384
    o.en_jeu = lambda: True
    assert {s["function"]["name"] for s in o.schemas_actifs()} == {"meteo"} and o.capacite_contexte() == 8192


class LLMBavard(LLMScripte):
    """Répète la même phrase sans fin, comme le petit modèle le 14/10."""

    async def diffuser(self, messages, outils=None, max_tokens=1024, reflexion=False):
        self.recus.append(messages)
        for _ in range(500):
            yield Evenement("texte", "Je ne peux pas envoyer un mail. ")
        yield Evenement("fin", reponse=Reponse(texte="…"))


def test_repetition_coupee(tmp_path):
    o = orchestrateur(tmp_path, [])
    o.llm = LLMBavard([])
    reponse = asyncio.run(o.repondre_texte("Bonjour", canal="texte"))
    assert reponse.count("Je ne peux pas envoyer un mail.") == 3  # coupé dès la 3e
    assert o.conversations["principale"][-1]["content"] == "Je ne peux pas envoyer un mail."


class LLMContexteDepasse(LLMScripte):
    """Refuse (400) toute requête qui contient encore de l'historique."""

    async def diffuser(self, messages, outils=None, max_tokens=1024, reflexion=False):
        self.recus.append(list(messages))
        if len(messages) > 2:
            requete = httpx.Request("POST", "http://127.0.0.1/v1/chat/completions")
            raise httpx.HTTPStatusError("400", request=requete, response=httpx.Response(400, request=requete))
        yield Evenement("texte", "Voilà.")
        yield Evenement("fin", reponse=Reponse(texte="Voilà."))


def test_reprise_sans_historique_apres_400(tmp_path):
    o = orchestrateur(tmp_path, [])
    o.llm = LLMContexteDepasse([])
    o.conversations["principale"] = [{"role": "user", "content": "avant"}, {"role": "assistant", "content": "ok"}]
    assert asyncio.run(o.repondre_texte("Bonjour", canal="texte")) == "Voilà."
    assert len(o.llm.recus) == 2 and len(o.llm.recus[1]) == 2


def test_filtre_balises_internes_dans_le_flux():
    from jarvis.agent.orchestrateur import FiltreBalises

    f = FiltreBalises()
    morceaux = ["Voici.\n<donn", "ees_externes>\nLa mer", " est bleue. 3 < 5 et a<b", "\n</donnees_externes>", " Fin."]
    sortie = "".join(f.ajouter(m) for m in morceaux) + f.vider()
    assert sortie == "Voici.\nLa mer est bleue. 3 < 5 et a<b\n Fin."


def test_longueur_de_reponse_adaptee_a_la_place(tmp_path):
    class LLMMesure(LLMScripte):
        async def diffuser(self, messages, outils=None, max_tokens=None, reflexion=False):
            self.max_tokens, self.reflexion = max_tokens, reflexion
            yield Evenement("texte", "ok")
            yield Evenement("fin", reponse=Reponse(texte="ok"))

    o = orchestrateur(tmp_path, [], [Factice("meteo", Niveau.LECTURE)])
    o.llm = LLMMesure([])
    o.capacite_contexte = lambda: 2500  # emplacement minuscule : pas de place pour réfléchir
    asyncio.run(o.repondre_texte("analyse en détail ma semaine de jeu et compare-la", canal="texte"))
    assert o.llm.reflexion is False and 200 <= o.llm.max_tokens <= 1024
    o.capacite_contexte = lambda: 300
    reponse = asyncio.run(o.repondre_texte("bonjour", canal="texte"))
    assert "mémoire de travail" in reponse
