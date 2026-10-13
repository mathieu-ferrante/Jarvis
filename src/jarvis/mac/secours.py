"""Mode secours du Mac (MAC-04, MULTI-06) : PC injoignable → petit modèle local (llama.cpp Metal).

Le modèle (Qwen3.5 2B, 1,3 Go) est chargé à la demande et déchargé après 10 minutes sans
usage : le Mac 8 Go n'est pas encombré. Seuls les outils du Mac sont disponibles, avec les mêmes
permissions (les confirmations passent par une boîte de dialogue). Jarvis annonce le mode réduit.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tarfile
import time
from pathlib import Path

from jarvis import chemins
from jarvis.agent.orchestrateur import Orchestrateur
from jarvis.llm.client import ClientLLM
from jarvis.mac import outils_mac
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat
from jarvis.outils.registre import Registre
from jarvis.securite.journal import Journal
from jarvis.securite.permissions import Demande
from jarvis.telechargement import Fichier, telecharger

log = logging.getLogger(__name__)
PORT = 8741
INACTIVITE_S = 600
PREFIXE = "(Mode réduit : le PC est injoignable.) "

LLAMA_MAC = Fichier("https://github.com/ggml-org/llama.cpp/releases/download/b11583/llama-b11583-bin-macos-arm64.tar.gz",
                    "llama.cpp/b11583-macos-arm64.tar.gz", 12112217,
                    "d23832f4b847a722a64c9bf57e518c3df81dfab325942182ff17792d5d33351f")
MODELE_MAC = Fichier("https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/f6d5376be1edb4d416d56da11e5397a961aca8ae/"
                     "Qwen3.5-2B-Q4_K_M.gguf", "Qwen3.5-2B-GGUF/Qwen3.5-2B-Q4_K_M.gguf", 1280835840,
                     "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223")


def installer() -> tuple[Path, Path]:
    """Télécharge (vérifié par SHA-256) llama.cpp macOS et le petit modèle. Renvoie (binaire, modèle)."""
    archive = telecharger(LLAMA_MAC, chemins.dossier_outils())
    dossier = archive.parent / "macos"
    if not any(dossier.rglob("llama-server")):
        with tarfile.open(archive) as t:
            t.extractall(dossier, filter="data")
    binaire = next(dossier.rglob("llama-server"))
    binaire.chmod(0o755)
    return binaire, telecharger(MODELE_MAC, chemins.dossier_modeles())


class OutilMacLocal(Outil):
    def __init__(self, definition: dict):
        self.nom = definition["nom"]
        self.description = definition["description"]
        self.parametres = definition["parametres"]
        self.niveau = {"lecture": Niveau.LECTURE, "reversible": Niveau.REVERSIBLE}.get(definition["niveau"], Niveau.IRREVERSIBLE)
        self.lit_contenu_externe = bool(definition.get("lit_contenu_externe"))

    async def executer(self, ctx: Contexte, **args) -> Resultat:
        ok, message = await asyncio.to_thread(outils_mac.executer, self.nom, args, None)
        return Resultat(ok, message, contenu_externe=self.lit_contenu_externe)


class ConfirmateurDialogue:
    """Confirmation par une boîte de dialogue macOS (refus après 60 s)."""

    async def demander(self, demande: Demande) -> bool:
        return await self.question(demande.question())

    async def question(self, texte: str) -> bool:
        script = (f"display dialog {outils_mac.echapper(texte)} with title \"Jarvis\" "
                  "buttons {\"Non\", \"Oui\"} default button \"Non\" giving up after 60")
        try:
            sortie = await asyncio.to_thread(outils_mac.osascript, script, 70)
        except Exception:  # noqa: BLE001
            return False
        return "button returned:Oui" in sortie


class Secours:
    def __init__(self, journal: Path | None = None):
        self.processus: subprocess.Popen | None = None
        self.dernier_usage = 0.0
        registre = Registre()
        for d in outils_mac.DEFINITIONS:
            if d["nom"] != "analyser_ecran":  # la vision exige le PC
                registre.ajouter(OutilMacLocal(d))
        self.client = ClientLLM(f"http://127.0.0.1:{PORT}", temperature=0.3)
        self.orchestrateur = Orchestrateur(self.client, registre, Journal(journal or chemins.dossier_donnees() / "journal-mac.sqlite"),
                                           ConfirmateurDialogue())
        self.orchestrateur.max_etapes = 5

    async def _demarrer(self) -> None:
        if self.processus and self.processus.poll() is None:
            return
        binaire, modele = await asyncio.to_thread(installer)
        self.processus = subprocess.Popen([str(binaire), "-m", str(modele), "--host", "127.0.0.1", "--port", str(PORT),
                                           "--offline", "--no-webui", "-ngl", "99", "-c", "8192", "--jinja", "-np", "1"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(240):
            if await self.client.disponible():
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("le modèle de secours n'a pas démarré")

    async def repondre(self, texte: str) -> str:
        self.dernier_usage = time.monotonic()
        try:
            await self._demarrer()
        except Exception as e:  # noqa: BLE001
            return f"{PREFIXE}Et le modèle de secours n'a pas pu démarrer ({e})."
        reponse = await self.orchestrateur.repondre_texte(texte, canal="texte", origine="texte:mac")
        self.dernier_usage = time.monotonic()
        return PREFIXE + reponse

    async def surveiller(self) -> None:
        """Décharge le modèle après 10 minutes sans usage (mémoire du Mac 8 Go)."""
        while True:
            await asyncio.sleep(30)
            if self.processus and self.processus.poll() is None and time.monotonic() - self.dernier_usage > INACTIVITE_S:
                self.processus.terminate()
                self.processus = None
                log.info("Modèle de secours déchargé")
