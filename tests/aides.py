"""Aides de test : faux modèle scripté et orchestrateur prêt à l'emploi."""

from __future__ import annotations

from jarvis.agent.orchestrateur import Orchestrateur
from jarvis.agent.taches import GestionnaireTaches
from jarvis.evenements import Bus
from jarvis.llm.client import AppelOutil, Evenement, Reponse
from jarvis.outils.registre import Registre
from jarvis.securite.journal import Journal
from jarvis.securite.permissions import ConfirmateurAutomatique


class LLMScripte:
    """Rejoue des réponses : une chaîne (texte) ou une liste [(outil, args), …] (appels d'outils)."""

    def __init__(self, script: list):
        self.script = list(script)
        self.recus: list[list[dict]] = []
        self.par_mot_cle: dict[str, list] = {}  # script dédié si la 1re demande contient le mot-clé

    async def diffuser(self, messages, outils=None, max_tokens=1024, reflexion=False):
        self.recus.append([dict(m) for m in messages])
        self.reflexions = getattr(self, 'reflexions', []) + [reflexion]
        premiere = next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")
        script = next((v for k, v in self.par_mot_cle.items() if k in premiere), self.script)
        etape = script.pop(0) if script else "Terminé."
        if isinstance(etape, str):
            for mot in etape.split(" "):
                yield Evenement("texte", mot + " ")
            yield Evenement("fin", reponse=Reponse(texte=etape))
        else:
            appels = [AppelOutil(f"a{i}", nom, args) for i, (nom, args) in enumerate(etape)]
            yield Evenement("fin", reponse=Reponse(appels=appels))

    async def discuter(self, messages, outils=None, max_tokens=1024):
        texte = ""
        async for e in self.diffuser(messages, outils):
            if e.type == "fin":
                return e.reponse
            texte += e.texte
        return Reponse(texte=texte)


def orchestrateur(tmp_path, script, outils=(), confirmations=False, **kwargs):
    registre = Registre()
    for o in outils:
        registre.ajouter(o)
    bus = Bus()
    o = Orchestrateur(LLMScripte(script), registre, Journal(tmp_path / "journal.sqlite"),
                      ConfirmateurAutomatique(confirmations), bus, **kwargs)
    o.services["taches"] = GestionnaireTaches(o, tmp_path / "taches.json")
    return o
