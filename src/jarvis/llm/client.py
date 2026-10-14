"""Client du serveur de modèles local (API compatible OpenAI de llama-server).

Seules les adresses locales sont acceptées : c'est la garantie, au niveau du code, qu'aucune
conversation ne part vers une IA distante (SEC-04).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

HOTES_LOCAUX = {"127.0.0.1", "localhost", "::1"}


class AdresseNonLocale(ValueError):
    pass


def verifier_locale(url: str) -> str:
    hote = (urlparse(url).hostname or "").lower()
    if hote not in HOTES_LOCAUX:
        raise AdresseNonLocale(f"Le modèle doit être servi en local, pas par « {hote} » (SEC-04)")
    return url.rstrip("/")


@dataclass
class AppelOutil:
    id: str
    nom: str
    args: dict


@dataclass
class Reponse:
    texte: str = ""
    appels: list[AppelOutil] = field(default_factory=list)
    jetons_prompt: int | None = None
    jetons_generes: int | None = None

    def message_assistant(self) -> dict:
        """Message à réinjecter dans l'historique (format OpenAI)."""
        message: dict = {"role": "assistant", "content": self.texte or None}
        if self.appels:
            message["tool_calls"] = [
                {"id": a.id, "type": "function",
                 "function": {"name": a.nom, "arguments": json.dumps(a.args, ensure_ascii=False)}}
                for a in self.appels
            ]
        return message


def _decoder_args(brut) -> dict:
    if isinstance(brut, dict):
        return brut
    try:
        valeur = json.loads(brut or "{}")
        return valeur if isinstance(valeur, dict) else {"valeur": valeur}
    except json.JSONDecodeError:
        return {"_illisible": brut}


@dataclass
class Evenement:
    """Évènement de diffusion : morceau de texte, ou réponse complète à la fin."""

    type: str  # "pensee", "texte" ou "fin"
    texte: str = ""
    reponse: Reponse | None = None


class ClientLLM:
    def __init__(self, url: str, temperature: float = 0.3, delai: float = 300):
        self.url = verifier_locale(url)
        self.temperature = temperature
        self._http = httpx.AsyncClient(timeout=delai)

    async def fermer(self) -> None:
        await self._http.aclose()

    def _corps(self, messages: list[dict], outils: list[dict] | None, max_tokens: int | None, flux: bool,
               reflexion: bool = False) -> dict:
        if max_tokens is None:  # par défaut : place pour la réflexion si elle est demandée
            max_tokens = 4096 if reflexion else 1024
        corps: dict = {"messages": messages, "max_tokens": max_tokens, "temperature": self.temperature,
                       "stream": flux, "chat_template_kwargs": {"enable_thinking": reflexion},
                       "cache_prompt": True,
                       # Échantillonneur DRY de llama.cpp : pénalise les séquences déjà produites (le
                       # 14/10, le petit modèle a répété la même phrase pendant 100 s sans lui)
                       "dry_multiplier": 0.8, "dry_base": 1.75, "dry_allowed_length": 2}
        if reflexion:
            corps["temperature"] = max(self.temperature, 0.6)  # valeur recommandée en mode réflexion
        if outils:
            corps["tools"] = outils
        return corps

    async def discuter(self, messages: list[dict], outils: list[dict] | None = None,
                       max_tokens: int | None = None, reflexion: bool = False) -> Reponse:
        r = await self._http.post(self.url + "/v1/chat/completions",
                                  json=self._corps(messages, outils, max_tokens, False, reflexion))
        r.raise_for_status()
        donnees = r.json()
        message = donnees["choices"][0]["message"]
        usage = donnees.get("usage") or {}
        return Reponse(
            texte=(message.get("content") or "").strip(),
            appels=[AppelOutil(tc.get("id") or f"appel{i}", tc["function"]["name"],
                               _decoder_args(tc["function"].get("arguments")))
                    for i, tc in enumerate(message.get("tool_calls") or [])],
            jetons_prompt=usage.get("prompt_tokens"), jetons_generes=usage.get("completion_tokens"),
        )

    async def diffuser(self, messages: list[dict], outils: list[dict] | None = None,
                       max_tokens: int | None = None, reflexion: bool = False) -> AsyncIterator[Evenement]:
        """Diffuse la réponse : « pensee » (réflexion, jamais lue), « texte », puis « fin » avec le tout."""
        texte = ""
        appels: dict[int, dict] = {}
        async with self._http.stream("POST", self.url + "/v1/chat/completions",
                                     json=self._corps(messages, outils, max_tokens, True, reflexion)) as r:
            r.raise_for_status()
            async for ligne in r.aiter_lines():
                if not ligne.startswith("data: ") or ligne.strip() == "data: [DONE]":
                    continue
                morceau = json.loads(ligne[6:])
                for choix in morceau.get("choices") or []:
                    delta = choix.get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield Evenement("pensee", delta["reasoning_content"])
                    if delta.get("content"):
                        texte += delta["content"]
                        yield Evenement("texte", delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        cible = appels.setdefault(tc.get("index", 0), {"id": "", "nom": "", "args": ""})
                        cible["id"] = tc.get("id") or cible["id"]
                        fonction = tc.get("function") or {}
                        cible["nom"] += fonction.get("name") or ""
                        cible["args"] += fonction.get("arguments") or ""
        reponse = Reponse(texte=texte.strip(), appels=[
            AppelOutil(a["id"] or f"appel{i}", a["nom"], _decoder_args(a["args"]))
            for i, a in sorted(appels.items())
        ])
        yield Evenement("fin", reponse=reponse)

    async def plonger(self, textes: list[str]) -> list[list[float]]:
        """Embeddings (serveur lancé avec --embedding)."""
        r = await self._http.post(self.url + "/v1/embeddings", json={"input": textes})
        r.raise_for_status()
        donnees = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in donnees]

    async def disponible(self) -> bool:
        try:
            return (await self._http.get(self.url + "/health", timeout=3)).status_code == 200
        except httpx.HTTPError:
            return False
