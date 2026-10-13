"""Cerveau minimal (lot J1) : conversation directe avec le modèle, en diffusion, sans outils.

Remplacé en fonctionnement normal par l'orchestrateur (lot J2) ; reste utile pour mesurer la
latence pure de la boucle vocale.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from jarvis.llm.client import ClientLLM

CONSIGNE = (
    "Tu es Jarvis, l'assistant vocal personnel de Mathieu, qui tourne entièrement sur son PC. "
    "Réponds en français, en une à trois phrases courtes : tes réponses sont lues à voix haute. "
    "Pas de Markdown, pas de listes. Si tu ne sais pas, dis-le."
)


class CerveauDirect:
    def __init__(self, client: ClientLLM, tours_gardes: int = 6):
        self.client = client
        self.historique: list[dict] = []
        self.tours_gardes = tours_gardes

    async def repondre(self, texte: str, canal: str = "voix") -> AsyncIterator[str]:
        maintenant = datetime.now().strftime("%A %d %B %Y, %H h %M")
        messages = [{"role": "system", "content": f"{CONSIGNE} Nous sommes le {maintenant}."},
                    *self.historique[-2 * self.tours_gardes:], {"role": "user", "content": texte}]
        reponse = ""
        async for evt in self.client.diffuser(messages, max_tokens=300):
            if evt.type == "texte":
                reponse += evt.texte
                yield evt.texte
        self.historique += [{"role": "user", "content": texte}, {"role": "assistant", "content": reponse}]
