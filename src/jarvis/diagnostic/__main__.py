"""Diagnostic J0 : mesure le matériel, les modèles et les briques vocales, puis tranche par la mesure.

Usage (depuis la racine du dépôt, voir diagnostic.ps1 qui prépare l'environnement) :
    python -m jarvis.diagnostic              # complet, sur le PC de jeu
    python -m jarvis.diagnostic --rapide     # petits modèles, pour valider le script ailleurs
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import psutil

from jarvis import chemins
from jarvis.diagnostic import catalogue, decision, llm, micro, rapport, reveil, stt, systeme, tts
from jarvis.telechargement import Fichier, telecharger

ETAPES = ("micro", "tts", "stt", "reveil", "llm")


def _options(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m jarvis.diagnostic", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rapide", action="store_true", help="petits modèles seulement (poste de développement)")
    p.add_argument("--avec-moe", action="store_true", help="mesurer aussi Gemma 4 26B-A4B (17 Go de plus)")
    p.add_argument("--avec-rocm", action="store_true", help="mesurer aussi llama.cpp ROCm (non officiel sur gfx1031)")
    p.add_argument("--sans-micro", action="store_true", help="sauter l'étape interactive au micro")
    p.add_argument("--etapes", default=",".join(ETAPES), help=f"étapes à lancer parmi {','.join(ETAPES)}")
    p.add_argument("--donnees", type=Path, help="dossier des modèles et outils (défaut : %%LOCALAPPDATA%%\\Jarvis)")
    p.add_argument("--resultats", type=Path, default=Path("diagnostic-resultats"),
                   help="dossier où écrire le rapport (défaut : diagnostic-resultats)")
    p.add_argument("--whisper-vulkan", type=Path,
                   help="dossier contenant un whisper-server.exe compilé avec Vulkan (facultatif)")
    p.add_argument("--fils", type=int, default=psutil.cpu_count(logical=False) or 4,
                   help="threads CPU pour la transcription (défaut : nombre de cœurs physiques)")
    p.add_argument("--oui", action="store_true", help="ne pas demander confirmation avant de télécharger")
    return p.parse_args(argv)


def _dossier_pour(f: Fichier) -> Path:
    racine = f.destination.split("/")[0]
    return chemins.dossier_outils() if racine in ("llama.cpp", "whisper.cpp") else chemins.dossier_modeles()


def _titre(texte: str) -> None:
    print(f"\n=== {texte} ===", flush=True)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    opts = _options(argv)
    if opts.donnees:
        import os

        os.environ["JARVIS_DONNEES"] = str(opts.donnees)
        chemins.memoriser_emplacement(opts.donnees)  # Jarvis retrouvera ce dossier au lancement
    etapes = {e.strip() for e in opts.etapes.split(",") if e.strip()}
    if opts.sans_micro:
        etapes.discard("micro")
    debut = time.monotonic()
    horodatage = datetime.now().strftime("%Y-%m-%d_%H%M")
    dossier = opts.resultats / horodatage
    resultats: dict = {"date": datetime.now().isoformat(timespec="minutes"), "rapide": opts.rapide,
                       "llama_cpp": catalogue.LLAMA_CPP_VERSION, "erreurs": []}
    chemin_json = dossier / "diagnostic.json"

    def sauver() -> None:
        resultats["duree_min"] = round((time.monotonic() - debut) / 60, 1)
        rapport.ecrire_json(resultats, chemin_json)

    _titre("Matériel")
    resultats["systeme"] = systeme.releve(chemins.dossier_donnees())
    s = resultats["systeme"]
    print(f"  {s['cpu']}, {s['ram_go']} Go, GPU : {', '.join(g['nom'] for g in s['gpus']) or '?'}")

    sel = catalogue.selection(opts.rapide, opts.avec_moe, opts.avec_rocm)
    if "llm" not in etapes:
        sel.llm, sel.backends = [], []
    if "stt" not in etapes:
        sel.stt = []
    fichiers = sel.fichiers()
    manquants = [f for f in fichiers if not (_dossier_pour(f) / f.destination).exists()]
    volume = sum(f.taille for f in manquants)
    _titre("Téléchargements")
    print(f"  {len(fichiers)} fichiers nécessaires, {len(manquants)} à télécharger ({volume / 1e9:.1f} Go)")
    print(f"  Destination : {chemins.dossier_donnees()}")
    print("  Sources : github.com (llama.cpp, whisper.cpp, openWakeWord, Kokoro) et huggingface.co (modèles).")
    print("  Rien n'est envoyé : ce sont de simples téléchargements de fichiers publics, vérifiés par SHA-256.")
    if manquants and not opts.oui:
        if input("  Continuer ? [o/N] ").strip().lower() not in ("o", "oui", "y"):
            print("  Abandon.")
            return 1
    for f in fichiers:
        try:
            telecharger(f, _dossier_pour(f), verifier_existant=False)
        except Exception as e:
            resultats["erreurs"].append(f"téléchargement {f.nom} : {e}")
            print(f"  ERREUR {f.nom} : {e}")
    sauver()

    modeles = chemins.dossier_modeles()
    enregistrements: dict = {"stt": [], "reveil": []}
    if "micro" in etapes:
        _titre("Micro")
        try:
            sortie = micro.etape_interactive(dossier / "micro", stt.phrases())
            resultats["micro"] = sortie["releve"]
            enregistrements = sortie
        except Exception as e:
            resultats["erreurs"].append(f"micro : {e}")
            print(f"  ERREUR micro : {e}")
        sauver()
    print("\n  La suite est automatique (de 30 min à 2 h selon le mode). Évitez d'utiliser le PC pendant ce temps.")

    synthetiseurs = []
    if etapes & {"tts", "stt", "reveil"}:
        _titre("Voix de synthèse")
        resultats["tts"] = []
        for voix in sel.tts:
            print(f"  {voix.cle}…", flush=True)
            mesure, synth = tts.mesurer_voix(voix, modeles, dossier / "ecoute")
            resultats["tts"].append(mesure)
            if synth:
                synthetiseurs.append(synth)
        # Une seule instance par moteur Kokoro suffit pour fabriquer le corpus
        vus, uniques = set(), []
        for synth in synthetiseurs:
            cle = (synth.voix.moteur, synth.voix.voix or synth.voix.cle)
            if cle not in vus:
                vus.add(cle)
                uniques.append(synth)
        synthetiseurs = uniques
        sauver()

    if "stt" in etapes and sel.stt:
        _titre("Transcription")
        corpus = stt.construire_corpus(synthetiseurs, dossier / "corpus", enregistrements["stt"])
        print(f"  corpus : {len(corpus)} extraits")
        whisper_bin = stt.installer_whisper_cpp(chemins.dossier_outils())
        resultats["stt"] = []
        for m in sel.stt:
            print(f"  {m.cle} (CPU, {opts.fils} threads)…", flush=True)
            resultats["stt"].append(stt.mesurer(m, corpus, modeles, whisper_bin, opts.fils,
                                                dossier / "journaux" / f"whisper-{m.cle}.log"))
            if opts.whisper_vulkan and m.moteur in ("whisper.cpp", "parakeet"):
                print(f"  {m.cle} (Vulkan)…", flush=True)
                resultats["stt"].append(stt.mesurer(m, corpus, modeles, opts.whisper_vulkan, opts.fils,
                                                    dossier / "journaux" / f"whisper-{m.cle}-vulkan.log",
                                                    variante="vulkan"))
            sauver()

    if "reveil" in etapes:
        _titre("Mot de réveil")
        resultats["reveil"] = reveil.mesurer(modeles, synthetiseurs, enregistrements["reveil"])
        sauver()
    del synthetiseurs

    if "llm" in etapes and sel.llm:
        resultats["llm"] = []
        resultats["peripheriques"] = {}
        for backend in sel.backends:
            _titre(f"Modèles de langage — llama.cpp {backend}")
            try:
                bin_dir = llm.installer(backend, chemins.dossier_outils())
            except Exception as e:
                resultats["erreurs"].append(f"installation llama.cpp {backend} : {e}")
                continue
            resultats["peripheriques"][backend] = llm.peripheriques(bin_dir)
            print("  périphériques : " + "; ".join(resultats["peripheriques"][backend]))
            if backend == "cpu":
                # Mode jeu : petits modèles sur CPU seul, débit et latence
                a_mesurer = [m for m in sel.llm if m.role in ("rapide", "test")]
            elif backend == "rocm":
                a_mesurer = [m for m in sel.llm if m.role in ("principal", "test")][:1]
            else:
                a_mesurer = sel.llm
            for m in a_mesurer:
                print(f"  {m.nom}…", flush=True)
                chemin = modeles / m.gguf.destination
                mmproj = modeles / m.mmproj.destination if m.mmproj else None
                try:
                    mesure = llm.mesurer_modele(m, chemin, mmproj, bin_dir, dossier,
                                                cpu_seul=backend == "cpu", complet=backend == "vulkan")
                except Exception as e:
                    mesure = {"modele": m.cle, "nom": m.nom, "role": m.role, "erreur": str(e),
                              "trace": traceback.format_exc()[-1500:]}
                mesure["backend"] = backend
                if backend == "rocm":
                    mesure["role"] = "essai_rocm"
                resultats["llm"].append(mesure)
                sauver()

    _titre("Décisions")
    resultats["decisions"] = decision.decider(resultats)
    sauver()
    chemin_md = rapport.ecrire_markdown(resultats, dossier / "rapport.md")
    for cle, dec in resultats["decisions"].items():
        print(f"  {cle} : {dec.get('choix', dec.get('estimation_ms'))}")
    print(f"\n  Rapport : {chemin_md.resolve()}")
    print(f"  Données : {chemin_json.resolve()}")
    print(f"  Durée : {resultats['duree_min']} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
