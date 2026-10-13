"""Mesure des modèles de langage avec llama.cpp : débit, latence, appel d'outils, français, vision.

Tout passe par les binaires officiels de llama.cpp, lancés en local :
- `llama-bench` pour le débit brut (traitement du prompt, génération) ;
- `llama-server` (API compatible OpenAI sur 127.0.0.1, mode hors ligne, sans interface web)
  pour la latence perçue, la batterie d'outils, des réponses en français et un test de vision.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import statistics
import struct
import subprocess
import time
import zipfile
import zlib
from pathlib import Path

import httpx

from jarvis.diagnostic import batterie, systeme
from jarvis.diagnostic.catalogue import LLAMA_CPP, LLAMA_CPP_VERSION, ModeleLLM
from jarvis.telechargement import telecharger

CONTEXTE = 8192
QUESTIONS_LATENCE = [
    "Quelle est la capitale de l'Australie ?",
    "Donne-moi une idée de dîner rapide.",
    "C'est quoi la différence entre un virus et une bactérie ?",
    "Pourquoi le ciel est bleu ?",
]
QUESTIONS_FRANCAIS = [
    "Explique-moi simplement comment fonctionne une carte graphique, en trois phrases.",
    "J'ai une soirée libre ce soir, propose-moi trois idées sans écran.",
    "Reformule plus poliment : « Envoie-moi ce fichier, j'en ai besoin maintenant. »",
]


# --- Installation et périphériques ----------------------------------------------------------


def installer(backend: str, dossier_outils: Path) -> Path:
    """Télécharge (vérifié) et décompresse llama.cpp pour `backend`. Renvoie le dossier des binaires."""
    archive = telecharger(LLAMA_CPP[backend], dossier_outils)
    dossier = archive.with_suffix("")
    if not (dossier / "llama-server.exe").exists():
        with zipfile.ZipFile(archive) as z:
            z.extractall(dossier)
    return dossier


def _executer(commande: list[str], delai: float) -> subprocess.CompletedProcess:
    return subprocess.run(commande, capture_output=True, text=True, timeout=delai,
                          encoding="utf-8", errors="replace")


def peripheriques(bin_dir: Path) -> list[str]:
    """Périphériques vus par llama.cpp, par ex. « Vulkan0: AMD Radeon RX 6750 XT (12272 MiB, …) »."""
    try:
        sortie = _executer([str(bin_dir / "llama-server.exe"), "--list-devices"], 120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"erreur : {e}"]
    lignes = (sortie.stdout + sortie.stderr).splitlines()
    return [ligne.strip() for ligne in lignes if re.match(r"\s+\w+\d+: ", ligne)]


# --- Débit brut -----------------------------------------------------------------------------


def bench(bin_dir: Path, modele: Path, repetitions: int = 3, cpu_seul: bool = False) -> dict:
    """Débit de traitement du prompt (pp512) et de génération (tg128), en jetons par seconde."""
    commande = [str(bin_dir / "llama-bench.exe"), "-m", str(modele), "-p", "512", "-n", "128",
                "-r", str(repetitions), "-o", "json"]
    commande += ["-ngl", "0"] if cpu_seul else ["-fitt", "1024", "-fitc", str(CONTEXTE)]
    try:
        sortie = _executer(commande, 1800)
    except subprocess.TimeoutExpired:
        return {"erreur": "llama-bench a dépassé 30 min"}
    if sortie.returncode != 0:
        return {"erreur": f"llama-bench code {sortie.returncode}", "journal": sortie.stderr[-2000:]}
    debut = sortie.stdout.find("[")
    try:
        lignes = json.loads(sortie.stdout[debut:])
    except json.JSONDecodeError:
        return {"erreur": "sortie llama-bench illisible", "journal": sortie.stdout[-2000:]}
    resultat: dict = {}
    for ligne in lignes:
        cle = "pp512_tok_s" if ligne.get("n_prompt") else "tg128_tok_s"
        resultat[cle] = round(ligne.get("avg_ts", 0.0), 1)
        resultat[cle.replace("tok_s", "ecart")] = round(ligne.get("stddev_ts", 0.0), 1)
        resultat["backend"] = ligne.get("backends")
        resultat["gpu"] = ligne.get("gpu_info")
        resultat["couches_gpu"] = ligne.get("n_gpu_layers")
    return resultat


# --- Serveur --------------------------------------------------------------------------------


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Serveur:
    """llama-server lancé pour la durée d'un bloc `with`, écoute uniquement en local."""

    def __init__(self, bin_dir: Path, modele: Path, mmproj: Path | None, journal: Path,
                 options: tuple[str, ...] = (), cpu_seul: bool = False):
        self.port = _port_libre()
        self.url = f"http://127.0.0.1:{self.port}"
        self.journal = journal
        self.commande = [
            str(bin_dir / "llama-server.exe"), "-m", str(modele),
            "--host", "127.0.0.1", "--port", str(self.port),
            "--offline", "--no-webui", "-c", str(CONTEXTE),
            "--reasoning", "off",  # pas de « réflexion » : réponses vocales rapides
            "--jinja", "-np", "1",
            "-lv", "4",  # journal détaillé : couches placées sur le GPU, mémoire prévue
            *options,
        ]
        if cpu_seul:
            self.commande += ["-ngl", "0"]
        if mmproj:
            self.commande += ["--mmproj", str(mmproj)]
        self.processus: subprocess.Popen | None = None
        self.duree_chargement_s: float | None = None

    def __enter__(self) -> Serveur:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self._fichier_journal = open(self.journal, "w", encoding="utf-8", errors="replace")
        debut = time.monotonic()
        self.processus = subprocess.Popen(self.commande, stdout=self._fichier_journal,
                                          stderr=subprocess.STDOUT)
        while time.monotonic() - debut < 600:
            if self.processus.poll() is not None:
                raise RuntimeError(f"llama-server s'est arrêté (code {self.processus.returncode}), "
                                   f"voir {self.journal}")
            try:
                if httpx.get(self.url + "/health", timeout=2).status_code == 200:
                    self.duree_chargement_s = round(time.monotonic() - debut, 1)
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.__exit__(None, None, None)
        raise RuntimeError("llama-server n'est pas prêt après 10 min")

    def __exit__(self, *_exc) -> None:
        if self.processus and self.processus.poll() is None:
            self.processus.terminate()
            try:
                self.processus.wait(15)
            except subprocess.TimeoutExpired:
                self.processus.kill()
        self._fichier_journal.close()

    def couches_gpu(self) -> str | None:
        texte = self.journal.read_text("utf-8", errors="replace")
        m = re.search(r"offloaded (\d+)/(\d+) layers to GPU", texte)
        return f"{m.group(1)}/{m.group(2)}" if m else None

    def memoire_prevue_go(self) -> float | None:
        """Mémoire du périphérique prévue par llama.cpp (modèle + contexte)."""
        texte = self.journal.read_text("utf-8", errors="replace")
        m = re.search(r"projected to use (\d+) MiB of device memory", texte)
        return round(int(m.group(1)) * 1.048576 / 1000, 2) if m else None


def _chat(url: str, messages: list[dict], outils: list | None = None, max_tokens: int = 256,
          delai: float = 300) -> dict:
    corps: dict = {"messages": messages, "max_tokens": max_tokens, "temperature": 0.0}
    if outils:
        corps["tools"] = outils
    r = httpx.post(url + "/v1/chat/completions", json=corps, timeout=delai)
    r.raise_for_status()
    return r.json()


def extraire_appels(reponse: dict) -> tuple[list[dict], str]:
    """Appels d'outils (nom + arguments décodés) et texte de la première réponse."""
    message = reponse["choices"][0]["message"]
    appels = []
    for tc in message.get("tool_calls") or []:
        fonction = tc.get("function", {})
        args = fonction.get("arguments") or "{}"
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_illisible": args}
        appels.append({"outil": fonction.get("name"), "args": args})
    return appels, (message.get("content") or "").strip()


_FIN_PHRASE = re.compile(r"\w.*?[.!?…](\s|$)", re.S)


def question_en_flux(url: str, messages: list[dict], outils: list | None = None) -> dict:
    """Pose une question en diffusion et chronomètre le premier jeton et la première phrase."""
    corps: dict = {"messages": messages, "max_tokens": 200, "temperature": 0.0, "stream": True,
                   "stream_options": {"include_usage": True}}
    if outils:
        corps["tools"] = outils
    debut = time.perf_counter()
    premier = phrase = None
    texte = ""
    timings: dict = {}
    with httpx.stream("POST", url + "/v1/chat/completions", json=corps, timeout=300) as r:
        r.raise_for_status()
        for ligne in r.iter_lines():
            if not ligne.startswith("data: ") or ligne == "data: [DONE]":
                continue
            morceau = json.loads(ligne[6:])
            timings = morceau.get("timings") or timings
            for choix in morceau.get("choices") or []:
                delta = choix.get("delta", {})
                contenu = delta.get("content") or ""
                if (contenu or delta.get("tool_calls")) and premier is None:
                    premier = time.perf_counter() - debut
                texte += contenu
                if phrase is None and _FIN_PHRASE.search(texte):
                    phrase = time.perf_counter() - debut
    fin = time.perf_counter() - debut
    return {
        "premier_jeton_ms": round(1000 * premier) if premier else None,
        "premiere_phrase_ms": round(1000 * (phrase or fin)),
        "total_ms": round(1000 * fin),
        "generation_tok_s": round(timings.get("predicted_per_second", 0.0), 1),
        "prompt_tok_s": round(timings.get("prompt_per_second", 0.0), 1),
        "jetons_prompt": timings.get("prompt_n"),
        "texte": texte.strip(),
    }


def mesurer_latence(url: str, bat: dict) -> dict:
    """Latence perçue avec le vrai contexte (consignes + 16 outils). 1re requête à froid, puis à chaud."""
    systeme_msg = {"role": "system", "content": bat["contexte_systeme"]}
    mesures = [question_en_flux(url, [systeme_msg, {"role": "user", "content": q}], bat["outils"])
               for q in QUESTIONS_LATENCE]
    froid, chaud = mesures[0], mesures[1:]

    def med(cle: str) -> float | None:
        valeurs = [m[cle] for m in chaud if m[cle] is not None]
        return round(statistics.median(valeurs)) if valeurs else None

    return {
        "froid_premier_jeton_ms": froid["premier_jeton_ms"],
        "chaud_premier_jeton_ms": med("premier_jeton_ms"),
        "chaud_premiere_phrase_ms": med("premiere_phrase_ms"),
        "generation_tok_s": med("generation_tok_s"),
        "jetons_contexte": froid["jetons_prompt"],
        "exemples": [{"question": q, "reponse": m["texte"]} for q, m in zip(QUESTIONS_LATENCE, mesures, strict=True)],
    }


def executer_batterie(url: str, bat: dict) -> list[batterie.Verdict]:
    verdicts = []
    for cas in bat["cas"]:
        messages = [{"role": "system", "content": bat["contexte_systeme"]},
                    {"role": "user", "content": cas["demande"]}]
        debut = time.perf_counter()
        try:
            appels, texte = extraire_appels(_chat(url, messages, bat["outils"]))
        except (httpx.HTTPError, KeyError, IndexError) as e:
            verdicts.append(batterie.Verdict(cas["id"], cas.get("tags", []), False, motif=f"erreur : {e}"))
            continue
        v = batterie.noter(cas, appels, texte)
        v.duree_s = round(time.perf_counter() - debut, 2)
        verdicts.append(v)
    return verdicts


def echantillons_francais(url: str, bat: dict) -> list[dict]:
    """Réponses libres, à relire par Mathieu (la qualité du français ne se note pas toute seule)."""
    resultat = []
    for q in QUESTIONS_FRANCAIS:
        messages = [{"role": "system", "content": bat["contexte_systeme"]}, {"role": "user", "content": q}]
        _, texte = extraire_appels(_chat(url, messages, max_tokens=300))
        resultat.append({"question": q, "reponse": texte, "semble_francais": batterie.semble_francais(texte)})
    return resultat


# --- Vision ---------------------------------------------------------------------------------


def image_test_png(largeur: int = 256, hauteur: int = 128) -> bytes:
    """Image synthétique : carré rouge à gauche, disque bleu à droite, fond blanc."""
    lignes = []
    for y in range(hauteur):
        ligne = bytearray([0])  # filtre PNG « aucun »
        for x in range(largeur):
            if 24 <= x < 104 and 24 <= y < 104:
                ligne += bytes((220, 30, 30))
            elif (x - 190) ** 2 + (y - 64) ** 2 < 40**2:
                ligne += bytes((30, 60, 220))
            else:
                ligne += bytes((255, 255, 255))
        lignes.append(bytes(ligne))

    def bloc(type_: bytes, donnees: bytes) -> bytes:
        return (struct.pack(">I", len(donnees)) + type_ + donnees
                + struct.pack(">I", zlib.crc32(type_ + donnees) & 0xFFFFFFFF))

    entete = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", entete)
            + bloc(b"IDAT", zlib.compress(b"".join(lignes))) + bloc(b"IEND", b""))


def test_vision(url: str) -> dict:
    image = base64.b64encode(image_test_png()).decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Décris en une phrase les formes et les couleurs de cette image."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
    ]}]
    debut = time.perf_counter()
    try:
        _, texte = extraire_appels(_chat(url, messages, max_tokens=120))
    except httpx.HTTPError as e:
        return {"reussi": False, "erreur": str(e)}
    t = texte.lower()
    reussi = "rouge" in t and "bleu" in t and any(m in t for m in ("carré", "carre", "rectangle"))
    return {"reussi": reussi, "reponse": texte, "duree_ms": round(1000 * (time.perf_counter() - debut))}


# --- Orchestration --------------------------------------------------------------------------


def mesurer_modele(modele: ModeleLLM, chemin: Path, mmproj: Path | None, bin_dir: Path,
                   dossier_resultats: Path, cpu_seul: bool = False, complet: bool = True) -> dict:
    """Toutes les mesures d'un modèle sur un backend. `complet=False` : débit et latence seulement."""
    bat = batterie.charger()
    resultat: dict = {"modele": modele.cle, "nom": modele.nom, "role": modele.role,
                      "llama_cpp": LLAMA_CPP_VERSION, "cpu_seul": cpu_seul}
    print("    débit brut (llama-bench)…", flush=True)
    resultat["bench"] = bench(bin_dir, chemin, cpu_seul=cpu_seul)

    vram_avant = systeme.vram_utilisee_max()
    suffixe = "cpu" if cpu_seul else bin_dir.name
    journal = dossier_resultats / "journaux" / f"llama-server-{modele.cle}-{suffixe}.log"
    try:
        with Serveur(bin_dir, chemin, mmproj if complet else None, journal, modele.options_serveur,
                     cpu_seul) as serveur:
            resultat["chargement_s"] = serveur.duree_chargement_s
            resultat["couches_gpu"] = serveur.couches_gpu()
            resultat["memoire_prevue_go"] = serveur.memoire_prevue_go()
            resultat["vram_go"] = round(max(systeme.vram_utilisee_max() - vram_avant, 0) / 1e9, 2)
            print("    latence perçue…", flush=True)
            resultat["latence"] = mesurer_latence(serveur.url, bat)
            if complet:
                print(f"    batterie d'outils ({len(bat['cas'])} cas)…", flush=True)
                verdicts = executer_batterie(serveur.url, bat)
                resultat["batterie"] = batterie.synthese(verdicts)
                resultat["batterie_detail"] = [v.__dict__ for v in verdicts]
                print("    réponses en français…", flush=True)
                resultat["francais"] = echantillons_francais(serveur.url, bat)
                if mmproj:
                    print("    vision…", flush=True)
                    resultat["vision"] = test_vision(serveur.url)
    except (RuntimeError, httpx.HTTPError, OSError) as e:
        resultat["erreur"] = str(e)
    return resultat
