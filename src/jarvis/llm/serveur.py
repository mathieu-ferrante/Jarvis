"""Gestion des processus llama-server : démarrage, arrêt, changement de modèle (mode jeu)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from jarvis import chemins, modeles
from jarvis.diagnostic.catalogue import LLAMA_CPP

log = logging.getLogger(__name__)


def dossier_binaires(backend: str) -> Path:
    archive = chemins.dossier_outils() / LLAMA_CPP[backend].destination
    dossier = archive.with_suffix("")
    if not (dossier / "llama-server.exe").exists():
        if not archive.exists():
            raise FileNotFoundError(f"llama.cpp {backend} absent : lancer `python -m jarvis installer`")
        with zipfile.ZipFile(archive) as z:
            z.extractall(dossier)
    return dossier


@dataclass
class Lancement:
    modele: str  # clé du catalogue, ou « embeddings »
    backend: str
    port: int
    contexte: int = 8192
    cpu_seul: bool = False
    vision: bool = True
    # Optimisations (PROVISOIRES, à confirmer par la mesure sur le PC de jeu) :
    speculatif: str = "aucun"  # aucun, brouillon (petit modèle), mtp, ngram
    brouillon: str = "qwen3.5-0.8b"  # modèle brouillon (même famille de tokeniseur que le principal)
    cache_kv: str = "q8_0"  # f16 ou q8_0 : q8_0 divise par deux la mémoire du contexte
    emplacements: int = 2  # slots llama-server (voir _commande)


class ServeurModele:
    """Un llama-server local. `relancer()` change de modèle ou de backend à chaud."""

    def __init__(self, journal: Path | None = None):
        self.processus: subprocess.Popen | None = None
        self.lancement: Lancement | None = None
        self.journal = journal or chemins.dossier_donnees() / "journaux" / "llama-server.log"

    @property
    def url(self) -> str:
        assert self.lancement
        return f"http://127.0.0.1:{self.lancement.port}"

    def _commande(self, l: Lancement) -> list[str]:
        binaires = dossier_binaires("cpu" if l.cpu_seul and l.backend == "vulkan" else l.backend)
        base = [str(binaires / "llama-server.exe"), "--host", "127.0.0.1", "--port", str(l.port),
                "--offline", "--no-webui"]
        if l.modele == "embeddings":
            return base + ["-np", "1", "-m", str(modeles.chemin(modeles.EMBEDDINGS)), "--embedding", "--pooling", "last",
                           "-ngl", "0", "-c", "2048"]
        m = modeles.modele_llm(l.modele)
        # La « réflexion » est pilotée requête par requête (chat_template_kwargs) : désactivée pour
        # les commandes simples, activée pour les demandes complexes ; les pensées vont dans
        # reasoning_content et ne sont jamais lues à voix haute.
        # Deux emplacements : la conversation garde son contexte fixe en cache pendant que les requêtes
        # annexes (souvenirs, suggestions, vision) passent par l'autre (llama-server choisit
        # l'emplacement dont le préfixe ressemble le plus). Le contexte total est doublé en conséquence.
        commande = base + ["-np", str(l.emplacements), "-c", str(l.contexte * l.emplacements),
                           "-m", str(modeles.chemin(m.gguf)), "--jinja",
                           "--reasoning-format", "deepseek", "-fa", "auto", *m.options_serveur]
        if l.cache_kv != "f16":
            commande += ["-ctk", l.cache_kv, "-ctv", l.cache_kv]
        if l.cpu_seul:
            commande += ["-ngl", "0"]
        elif l.speculatif == "brouillon" and l.brouillon and l.brouillon != l.modele:
            b = modeles.modele_llm(l.brouillon)
            if modeles.chemin(b.gguf).exists():
                commande += ["-md", str(modeles.chemin(b.gguf)), "--spec-type", "draft-simple",
                             "--spec-draft-n-max", "8", "-ngld", "99"]
        elif l.speculatif in ("mtp", "ngram"):
            commande += ["--spec-type", "draft-mtp" if l.speculatif == "mtp" else "ngram-cache"]
        if l.vision and m.mmproj and modeles.chemin(m.mmproj).exists():
            commande += ["--mmproj", str(modeles.chemin(m.mmproj))]
        return commande

    async def demarrer(self, lancement: Lancement, delai: float = 300) -> None:
        try:
            await self._demarrer(lancement, delai)
        except RuntimeError:
            if lancement.speculatif == "aucun" and lancement.cache_kv == "f16":
                raise
            # Une optimisation non prise en charge ne doit pas empêcher Jarvis de démarrer
            log.warning("llama-server refuse les optimisations, relance sans (voir %s)", self.journal)
            await self._demarrer(Lancement(**{**lancement.__dict__, "speculatif": "aucun", "cache_kv": "f16"}), delai)

    async def _demarrer(self, lancement: Lancement, delai: float) -> None:
        await self.arreter()
        self.lancement = lancement
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        sortie = open(self.journal, "a", encoding="utf-8", errors="replace")
        commande = self._commande(lancement)
        log.info("Démarrage de llama-server : %s", " ".join(commande))
        self.processus = subprocess.Popen(commande, stdout=sortie, stderr=subprocess.STDOUT,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        debut = time.monotonic()
        async with httpx.AsyncClient() as http:
            while time.monotonic() - debut < delai:
                if self.processus.poll() is not None:
                    raise RuntimeError(f"llama-server arrêté (code {self.processus.returncode}), voir {self.journal}")
                try:
                    if (await http.get(self.url + "/health", timeout=2)).status_code == 200:
                        log.info("llama-server prêt en %.1f s", time.monotonic() - debut)
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.3)
        raise RuntimeError("llama-server n'est pas prêt")

    async def arreter(self) -> None:
        if self.processus and self.processus.poll() is None:
            self.processus.terminate()
            try:
                await asyncio.to_thread(self.processus.wait, 15)
            except subprocess.TimeoutExpired:
                self.processus.kill()
        self.processus = None

    async def relancer(self, **changements) -> None:
        assert self.lancement
        nouveau = Lancement(**{**self.lancement.__dict__, **changements})
        if nouveau != self.lancement or not self.actif:
            await self.demarrer(nouveau)

    @property
    def actif(self) -> bool:
        return self.processus is not None and self.processus.poll() is None
