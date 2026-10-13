"""Plongements (embeddings) pour la recherche sémantique locale (MEM-02).

- `PlongeurLocal` : modèle Qwen3-Embedding servi par llama-server sur 127.0.0.1 ;
- `PlongeurHachage` : repli sans modèle (n-grammes de caractères hachés), utilisé si le serveur
  d'embeddings est indisponible et dans les tests. Moins fin, mais toujours local.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

import httpx
import numpy as np

from jarvis.llm.client import verifier_locale

DIMENSION_HACHAGE = 512


def normaliser(vecteurs: np.ndarray) -> np.ndarray:
    normes = np.linalg.norm(vecteurs, axis=1, keepdims=True)
    return (vecteurs / np.maximum(normes, 1e-9)).astype(np.float32)


class PlongeurHachage:
    identifiant = "hachage-v1"

    def plonger(self, textes: list[str]) -> np.ndarray:
        sortie = np.zeros((len(textes), DIMENSION_HACHAGE), dtype=np.float32)
        for i, texte in enumerate(textes):
            t = unicodedata.normalize("NFKD", texte.lower())
            t = "".join(c for c in t if not unicodedata.combining(c))
            for mot in re.findall(r"\w+", t):
                mot = f" {mot} "
                for n in (3, 4):
                    for j in range(len(mot) - n + 1):
                        h = int.from_bytes(hashlib.blake2b(mot[j:j + n].encode(), digest_size=4).digest(), "little")
                        sortie[i, h % DIMENSION_HACHAGE] += 1.0 if (h >> 31) & 1 else -1.0
        return normaliser(sortie)


class PlongeurLocal:
    """Qwen3-Embedding-0.6B via llama-server --embedding (consigne de requête recommandée par Qwen)."""

    identifiant = "qwen3-embedding-0.6b"
    CONSIGNE_REQUETE = "Instruct: Retrouver les souvenirs et documents pertinents pour cette demande\nQuery: "

    def __init__(self, url: str):
        self.url = verifier_locale(url)

    def plonger(self, textes: list[str], requete: bool = False) -> np.ndarray:
        if requete:
            textes = [self.CONSIGNE_REQUETE + t for t in textes]
        r = httpx.post(self.url + "/v1/embeddings", json={"input": textes}, timeout=60)
        r.raise_for_status()
        donnees = sorted(r.json()["data"], key=lambda d: d["index"])
        return normaliser(np.array([d["embedding"] for d in donnees], dtype=np.float32))


class PlongeurAvecRepli:
    """Essaie le modèle local ; s'il ne répond pas, bascule sur le hachage (et le signale)."""

    def __init__(self, principal: PlongeurLocal | None):
        self.principal = principal
        self.repli = PlongeurHachage()

    @property
    def identifiant(self) -> str:
        return self.principal.identifiant if self.principal and self._disponible() else self.repli.identifiant

    def _disponible(self) -> bool:
        try:
            return httpx.get(self.principal.url + "/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            return False

    def plonger(self, textes: list[str], requete: bool = False) -> tuple[np.ndarray, str]:
        if self.principal:
            try:
                return self.principal.plonger(textes, requete), self.principal.identifiant
            except httpx.HTTPError:
                pass
        return self.repli.plonger(textes), self.repli.identifiant
