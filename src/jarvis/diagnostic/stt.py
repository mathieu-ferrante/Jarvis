"""Transcription : latence et taux d'erreur de mots (WER) en français, sur CPU (et Vulkan si fourni).

Corpus de test :
- phrases de commande synthétisées par chacune des voix disponibles (plusieurs « locuteurs ») ;
- les mêmes avec un bruit de ventilateur simulé à 10 dB de rapport signal sur bruit ;
- les enregistrements de Mathieu au micro, s'il a fait l'étape micro (le vrai test).
"""

from __future__ import annotations

import re
import socket
import statistics
import subprocess
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import httpx
import numpy as np

from jarvis.diagnostic import audio
from jarvis.diagnostic.catalogue import WHISPER_CPP_CPU, ModeleSTT
from jarvis.telechargement import telecharger

RSB_BRUIT_DB = 10


def phrases() -> list[str]:
    texte = resources.files("jarvis.diagnostic").joinpath("donnees/phrases_stt.txt").read_text("utf-8")
    return [ligne.strip() for ligne in texte.splitlines() if ligne.strip() and not ligne.startswith("#")]


def normaliser(texte: str) -> str:
    """Pour le WER : minuscules, sans ponctuation ni tirets, apostrophes séparées, accents conservés."""
    texte = unicodedata.normalize("NFC", texte.lower())
    texte = texte.replace("’", "'").replace("'", " ").replace("-", " ")
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def wer(reference: str, hypothese: str) -> float:
    import jiwer

    ref, hyp = normaliser(reference), normaliser(hypothese)
    if not ref:
        return 0.0 if not hyp else 1.0
    return float(jiwer.wer(ref, hyp))


@dataclass
class Extrait:
    id: str
    texte: str
    condition: str  # "propre", "bruit" ou "micro"
    chemin: Path
    duree_s: float

    def audio16k(self) -> np.ndarray:
        son, taux = audio.lire_wav(self.chemin)
        return audio.reechantillonner(son, taux)


def construire_corpus(synthetiseurs: list, dossier: Path, enregistrements_micro: list[dict]) -> list[Extrait]:
    """Fabrique les extraits de test (WAV 16 kHz) à partir des voix de synthèse et du micro."""
    corpus: list[Extrait] = []
    bruit = audio.bruit_pc(audio.TAUX_STT * 30)
    for synth in synthetiseurs:
        for i, phrase in enumerate(phrases()):
            son, taux = synth.synthetiser(phrase)
            son = np.concatenate([audio.silence(0.3), audio.reechantillonner(son, taux), audio.silence(0.3)])
            duree = len(son) / audio.TAUX_STT
            base = f"{synth.voix.cle}-{i:02d}"
            corpus.append(Extrait(base, phrase, "propre",
                                  audio.ecrire_wav(dossier / f"{base}-propre.wav", son, audio.TAUX_STT), duree))
            bruyant = audio.melanger(son, np.roll(bruit, i * 7919), RSB_BRUIT_DB)
            corpus.append(Extrait(base, phrase, "bruit",
                                  audio.ecrire_wav(dossier / f"{base}-bruit.wav", bruyant, audio.TAUX_STT), duree))
    for e in enregistrements_micro:
        corpus.append(Extrait(e["id"], e["texte"], "micro", Path(e["chemin"]), e["duree_s"]))
    return corpus


# --- Moteurs --------------------------------------------------------------------------------


class FasterWhisper:
    def __init__(self, dossier_modele: Path, fils: int):
        from faster_whisper import WhisperModel

        self.modele = WhisperModel(str(dossier_modele), device="cpu", compute_type="int8",
                                   cpu_threads=fils, local_files_only=True)

    def transcrire(self, extraits: list[Extrait]) -> list[tuple[str, float]]:
        resultats = []
        for e in extraits:
            son = e.audio16k()
            debut = time.perf_counter()
            segments, _ = self.modele.transcribe(son, language="fr", beam_size=1, vad_filter=False,
                                                 condition_on_previous_text=False, without_timestamps=True)
            texte = " ".join(s.text.strip() for s in segments)
            resultats.append((texte, time.perf_counter() - debut))
        return resultats

    def fermer(self) -> None:
        del self.modele


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WhisperCppServeur:
    """whisper-server chargé une fois, interrogé en local (127.0.0.1) pour chaque extrait."""

    def __init__(self, bin_dir: Path, modele: Path, fils: int, journal: Path):
        self.port = _port_libre()
        journal.parent.mkdir(parents=True, exist_ok=True)
        self._journal = open(journal, "w", encoding="utf-8", errors="replace")
        self.processus = subprocess.Popen(
            [str(bin_dir / "whisper-server.exe"), "-m", str(modele), "-t", str(fils), "-l", "fr", "-nt",
             "--host", "127.0.0.1", "--port", str(self.port)],
            stdout=self._journal, stderr=subprocess.STDOUT,
        )
        url = f"http://127.0.0.1:{self.port}/"
        debut = time.monotonic()
        while time.monotonic() - debut < 300:
            if self.processus.poll() is not None:
                raise RuntimeError(f"whisper-server arrêté (code {self.processus.returncode})")
            try:
                httpx.get(url, timeout=2)
                return
            except httpx.HTTPError:
                time.sleep(0.5)
        raise RuntimeError("whisper-server n'est pas prêt après 5 min")

    def transcrire(self, extraits: list[Extrait]) -> list[tuple[str, float]]:
        resultats = []
        for e in extraits:
            donnees = e.chemin.read_bytes()
            debut = time.perf_counter()
            r = httpx.post(f"http://127.0.0.1:{self.port}/inference", timeout=300,
                           files={"file": (e.chemin.name, donnees, "audio/wav")},
                           data={"response_format": "json", "temperature": "0"})
            r.raise_for_status()
            resultats.append((r.json().get("text", "").strip(), time.perf_counter() - debut))
        return resultats

    def fermer(self) -> None:
        if self.processus.poll() is None:
            self.processus.terminate()
            try:
                self.processus.wait(10)
            except subprocess.TimeoutExpired:
                self.processus.kill()
        self._journal.close()


class ParakeetCli:
    """parakeet-cli de whisper.cpp. Il n'a pas de mode serveur : on lance un processus par lot et
    on retranche le temps de chargement, estimé sur un lot d'un seul extrait."""

    def __init__(self, bin_dir: Path, modele: Path, fils: int):
        self.commande = [str(bin_dir / "parakeet-cli.exe"), "-m", str(modele), "-t", str(fils), "-np", "-otxt"]

    def _lot(self, extraits: list[Extrait]) -> tuple[list[str], float]:
        for e in extraits:
            e.chemin.with_suffix(".wav.txt").unlink(missing_ok=True)
        debut = time.perf_counter()
        sortie = subprocess.run(self.commande + [str(e.chemin) for e in extraits], capture_output=True,
                                text=True, timeout=900, encoding="utf-8", errors="replace")
        duree = time.perf_counter() - debut
        if sortie.returncode != 0:
            raise RuntimeError(f"parakeet-cli code {sortie.returncode} : {sortie.stderr[-500:]}")
        textes = []
        for e in extraits:
            fichier = e.chemin.with_suffix(".wav.txt")
            textes.append(fichier.read_text("utf-8", errors="replace").strip() if fichier.exists() else "")
        return textes, duree

    def transcrire(self, extraits: list[Extrait]) -> list[tuple[str, float]]:
        if not extraits:
            return []
        _, duree_un = self._lot(extraits[:1])
        textes, duree_tous = self._lot(extraits)
        if len(extraits) > 1:
            par_extrait = max((duree_tous - duree_un) / (len(extraits) - 1), 0.0)
        else:
            par_extrait = duree_un
        self.chargement_s = round(max(duree_un - par_extrait, 0.0), 2)
        # Faute de chronométrage individuel, on répartit le temps selon la durée des extraits.
        total_audio = sum(e.duree_s for e in extraits)
        temps_calcul = par_extrait * len(extraits)
        return [(t, temps_calcul * e.duree_s / total_audio) for t, e in zip(textes, extraits, strict=True)]

    def fermer(self) -> None:
        pass


def installer_whisper_cpp(dossier_outils: Path) -> Path:
    archive = telecharger(WHISPER_CPP_CPU, dossier_outils)
    dossier = archive.with_suffix("")
    if not (dossier / "Release" / "whisper-server.exe").exists():
        with zipfile.ZipFile(archive) as z:
            z.extractall(dossier)
    return dossier / "Release"


# --- Mesure ---------------------------------------------------------------------------------


def mesurer(modele: ModeleSTT, corpus: list[Extrait], dossier_modeles: Path, whisper_bin: Path | None,
            fils: int, journal: Path, variante: str = "cpu") -> dict:
    resultat: dict = {"modele": modele.cle, "moteur": modele.moteur, "variante": variante, "fils": fils}
    debut = time.perf_counter()
    try:
        if modele.moteur == "faster-whisper":
            moteur = FasterWhisper(dossier_modeles / modele.dossier, fils)
        elif modele.moteur == "whisper.cpp":
            moteur = WhisperCppServeur(whisper_bin, dossier_modeles / modele.fichiers[0].destination, fils, journal)
        else:
            moteur = ParakeetCli(whisper_bin, dossier_modeles / modele.fichiers[0].destination, fils)
        resultat["chargement_s"] = round(time.perf_counter() - debut, 2)
        moteur.transcrire(corpus[:1])  # préchauffage
        sorties = moteur.transcrire(corpus)
        if isinstance(moteur, ParakeetCli):
            resultat["chargement_s"] = moteur.chargement_s
        moteur.fermer()
    except Exception as e:  # un moteur qui plante ne doit pas arrêter le diagnostic
        resultat["erreur"] = f"{type(e).__name__} : {e}"
        return resultat

    par_condition: dict[str, list] = {}
    exemples = []
    for extrait, (texte, duree) in zip(corpus, sorties, strict=True):
        par_condition.setdefault(extrait.condition, []).append((extrait, texte, duree))
        if len(exemples) < 6 or extrait.condition == "micro":
            exemples.append({"condition": extrait.condition, "reference": extrait.texte, "transcription": texte})
    for condition, lignes in par_condition.items():
        resultat[f"wer_{condition}"] = round(statistics.mean(wer(e.texte, t) for e, t, _ in lignes), 3)
    toutes = [d for lignes in par_condition.values() for _, _, d in lignes]
    resultat["latence_mediane_ms"] = round(1000 * statistics.median(toutes))
    resultat["latence_max_ms"] = round(1000 * max(toutes))
    duree_audio = statistics.median(e.duree_s for e in corpus)
    resultat["duree_audio_mediane_s"] = round(duree_audio, 2)
    resultat["facteur_temps_reel"] = round(sum(toutes) / sum(e.duree_s for e in corpus), 3)
    resultat["exemples"] = exemples
    return resultat
