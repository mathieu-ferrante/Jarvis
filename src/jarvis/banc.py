"""Banc de performance et batterie de commandes (NF-02, IA-01, extensions §2.3).

    python -m jarvis banc                 # tout : commandes + performance
    python -m jarvis banc --commandes     # seulement la batterie (taux de réussite du premier coup)
    python -m jarvis banc --perf          # seulement les mesures PERF
    python -m jarvis banc --url http://127.0.0.1:8731   # serveur de modèles déjà lancé

Le rapport (Markdown + JSON) est écrit dans `banc-resultats/<date>/` et comparé au précédent :
toute dégradation de plus de 10 % d'un budget est signalée (à justifier dans PLAN.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime
from importlib import resources
from pathlib import Path

from jarvis import config as module_config
from jarvis.agent import commandes_rapides, contexte, routeur
from jarvis.diagnostic import batterie
from jarvis.llm.client import ClientLLM

SEUIL_REGRESSION = 0.10
# Budgets (extensions §2.1) : (clé, objectif, sens) ; sens -1 = plus petit est meilleur
BUDGETS = {
    "PERF-01_latence_voix_ms": (1000, -1),
    "PERF-02_latence_action_ms": (1200, -1),
    "PERF-05_generation_tok_s": (40, 1),
    "PERF-06_contexte_fixe_ms": (50, -1),
    "PERF-07_cpu_repos_pct": (2, -1),
    "PERF-09_demarrage_s": (15, -1),
    "PERF-10_bascule_jeu_s": (3, -1),
    "PERF-13_recherche_memoire_ms": (50, -1),
    "NF-02_taux_commandes": (0.90, 1),
}


def charger_batterie() -> dict:
    return json.loads(resources.files("jarvis").joinpath("donnees/batterie_commandes.json").read_text("utf-8"))


# --- Batterie de commandes ------------------------------------------------------------------


async def batterie_commandes(client: ClientLLM, config) -> dict:
    from jarvis.llm.client import AppelOutil  # noqa: F401  (format des appels)
    from jarvis.outils.registre import Registre

    bat = charger_batterie()
    registre = Registre().charger_tout()
    schemas = registre.schemas()
    moment = datetime.fromisoformat(bat["moment"])
    verdicts, durees, rapides = [], [], 0
    for cas in bat["cas"]:
        debut = time.perf_counter()
        commande = commandes_rapides.reconnaitre(cas["demande"], lambda n: True, lambda n: True)
        if commande is not None and commande.outil in registre:
            appels, texte = [{"outil": commande.outil, "args": commande.args}], ""
            rapides += 1
        else:
            prefixe = contexte.contexte_variable("voix", config.initiative.ville_meteo, False, None, moment)
            messages = [{"role": "system", "content": contexte.CONSIGNES},
                        {"role": "user", "content": f"{prefixe}\n{cas['demande']}"}]
            reflexion = routeur.besoin_reflexion(cas["demande"], config.llm.reflexion)
            try:
                r = await client.discuter(messages, schemas, max_tokens=600, reflexion=reflexion)
                appels, texte = [{"outil": a.nom, "args": a.args} for a in r.appels], r.texte
            except Exception as e:  # noqa: BLE001
                verdicts.append(batterie.Verdict(cas["id"], cas.get("tags", []), False, motif=f"erreur : {e}"))
                continue
        v = batterie.noter(cas, appels, texte)
        v.duree_s = round(time.perf_counter() - debut, 2)
        durees.append(v.duree_s)
        verdicts.append(v)
        print(f"  {'✓' if v.reussi else '✗'} {cas['id']:24} {v.duree_s:5.1f} s  {v.motif[:80]}", flush=True)
    synthese = batterie.synthese(verdicts)
    synthese["chemin_rapide"] = rapides
    synthese["duree_mediane_s"] = round(statistics.median(durees), 2) if durees else None
    synthese["nombre_outils"] = len(registre.outils)
    return synthese


# --- Mesures de performance -----------------------------------------------------------------


async def mesurer_generation(client: ClientLLM) -> dict:
    """PERF-05 (génération) et PERF-06 (contexte fixe en cache) avec les vraies consignes et les vrais outils."""
    import httpx

    from jarvis.outils.registre import Registre

    schemas = Registre().charger_tout().schemas()
    resultats = []
    for question in (["Raconte-moi en détail l'histoire de la Tour Eiffel.",
                                  "Explique-moi le fonctionnement d'un moteur électrique, en détail."]):
        corps = {"messages": [{"role": "system", "content": contexte.CONSIGNES},
                              {"role": "user", "content": question}],
                 "tools": schemas, "max_tokens": 200, "temperature": 0, "cache_prompt": True,
                 "chat_template_kwargs": {"enable_thinking": False}}
        async with httpx.AsyncClient(timeout=300) as http:
            r = await http.post(client.url + "/v1/chat/completions", json=corps)
            timings = r.json().get("timings", {})
        resultats.append(timings)
    premier, second = resultats
    return {
        "PERF-05_generation_tok_s": round(second.get("predicted_per_second", 0), 1),
        "PERF-06_contexte_fixe_ms": round(second.get("prompt_ms", 0)),
        "contexte_fixe_jetons_traites_1re": premier.get("prompt_n"),
        "contexte_fixe_jetons_traites_2e": second.get("prompt_n"),
    }


def mesurer_cpu_repos(secondes: int = 20) -> dict:
    """PERF-07 : coût CPU du mot de réveil + détection de parole sur du silence (bruit faible)."""
    import psutil

    from jarvis.diagnostic import audio
    from jarvis.voix import moteurs

    reveil, vad = moteurs.DetecteurReveil(), moteurs.DetecteurParole()
    son = audio.en_int16(audio.bruit_pc(16000 * secondes) * 0.01)
    debut_cpu, debut = time.process_time(), time.perf_counter()
    for i in range(0, len(son) - 1280, 1280):
        reveil.traiter(son[i:i + 1280])
        if i % 2560 == 0:
            vad.probabilite(son[i:i + 1280])
        attente = (i / 16000) - (time.perf_counter() - debut)
        if attente > 0:
            time.sleep(attente)  # temps réel, comme en écoute
    cpu = time.process_time() - debut_cpu
    duree = time.perf_counter() - debut
    return {"PERF-07_cpu_repos_pct": round(100 * cpu / duree / (psutil.cpu_count() or 1), 2)}


def mesurer_memoire(n: int = 10_000, url_embeddings: str | None = None) -> dict:
    """PERF-13 : recherche dans 10 000 souvenirs."""
    import tempfile

    from jarvis.memoire.stockage import Memoire
    from jarvis.memoire.vecteurs import PlongeurHachage

    with tempfile.TemporaryDirectory() as d:
        plongeur = PlongeurHachage()
        m = Memoire(Path(d) / "m.sqlite", plongeur=plongeur)
        sujets = ["jeu", "musique", "travail", "famille", "sport", "cuisine", "projet", "voiture", "film", "voyage"]
        lignes = [(f"Mathieu a noté le fait numéro {i} à propos de {sujets[i % 10]} et de la variante {i * 7 % 97}",)
                  for i in range(n)]
        vecteurs = plongeur.plonger([t for (t,) in lignes])
        maintenant = datetime.now().isoformat(timespec="seconds")
        with m._cnx:
            m._cnx.executemany("INSERT INTO faits (texte, source, cree, modifie, vecteur, plongeur) VALUES (?,?,?,?,?,?)",
                               [(t, "banc", maintenant, maintenant, v.tobytes(), plongeur.identifiant)
                                for (t,), v in zip(lignes, vecteurs, strict=True)])
        m.rechercher("préchauffage")
        durees = []
        for q in ["qu'est-ce que je sais sur la cuisine", "les projets de Mathieu", "voiture variante 12"] * 5:
            t = time.perf_counter()
            m.rechercher(q)
            durees.append(1000 * (time.perf_counter() - t))
        m.fermer()
    return {"PERF-13_recherche_memoire_ms": round(statistics.median(durees), 1), "souvenirs": n,
            "note_memoire": "plongements par hachage ; avec Qwen3-Embedding, ajouter le temps d'un plongement de requête"}


async def mesurer_demarrage_et_bascule(config) -> dict:
    """PERF-09 (serveur prêt + contexte préchauffé) et PERF-10 (VRAM libérée à l'entrée en jeu)."""
    from jarvis.agent.contexte import CONSIGNES
    from jarvis.diagnostic.systeme import vram_utilisee_max
    from jarvis.llm.serveur import Lancement, ServeurModele
    from jarvis.outils.registre import Registre

    c = config.llm
    serveur = ServeurModele()
    vram_avant = vram_utilisee_max()
    debut = time.perf_counter()
    await serveur.demarrer(Lancement(c.principal, c.backend, c.port + 50, c.contexte, speculatif=c.speculatif,
                                     brouillon=c.brouillon, cache_kv=c.cache_kv))
    client = ClientLLM(serveur.url)
    await client.discuter([{"role": "system", "content": CONSIGNES}, {"role": "user", "content": "Bonjour."}],
                          Registre().charger_tout().schemas(), max_tokens=1)
    pret = time.perf_counter() - debut
    vram_chargee = vram_utilisee_max()
    debut = time.perf_counter()
    await serveur.arreter()
    for _ in range(30):
        if vram_utilisee_max() < vram_avant + 0.5e9:
            break
        await asyncio.sleep(0.1)
    bascule = time.perf_counter() - debut
    await client.fermer()
    return {"PERF-09_demarrage_s": round(pret, 1), "PERF-10_bascule_jeu_s": round(bascule, 2),
            "vram_modele_go": round((vram_chargee - vram_avant) / 1e9, 2),
            "note_demarrage": "serveur de modèles + préchauffage du contexte ; l'import Python s'y ajoute (~2 s)"}


async def mesurer_latences_voix(client: ClientLLM, config) -> dict:
    """PERF-01 / PERF-02 : vraie chaîne vocale (Parakeet, Piper, modèle), micro simulé en temps réel."""
    from jarvis.agent.orchestrateur import Orchestrateur
    from jarvis.diagnostic import audio
    from jarvis.evenements import Bus
    from jarvis.outils.registre import Registre
    from jarvis.securite.journal import Journal
    from jarvis.securite.permissions import ConfirmateurAutomatique
    from jarvis.voix import moteurs
    from jarvis.voix.audio_es import EntreeSimulee, SortieSimulee
    from jarvis.voix.boucle import BoucleVocale, ParametresBoucle

    stt = moteurs.creer_transcripteur(config.voix)
    tts = moteurs.Synthese(config.voix.tts)
    import tempfile

    resultats: dict = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        bus = Bus()
        journal = Journal(Path(d) / "j.sqlite")
        orchestrateur = Orchestrateur(client, Registre().charger_tout(), journal,
                                      ConfirmateurAutomatique(False), bus, config=config)
        await orchestrateur.repondre_texte("Bonjour.", canal="voix")  # préchauffage
        for cle, phrases in [("PERF-01_latence_voix_ms", ["Quelle est la capitale de l'Australie ?",
                                                          "Combien de pattes a une araignée ?",
                                                          "Qui a peint la Joconde ?"]),
                             ("PERF-02_latence_action_ms", ["Quelle heure est-il ?"] * 3)]:
            latences = []
            for phrase in phrases:
                son, taux = tts.synthetiser(phrase)
                entree = EntreeSimulee([audio.silence(0.3), audio.reechantillonner(son, taux)], temps_reel=True,
                                       silence_final_s=2.5)
                boucle = BoucleVocale(entree, SortieSimulee(), moteurs.DetecteurReveilFactice(-200, 10**9),
                                      moteurs.DetecteurParole(), stt, tts, orchestrateur,
                                      ParametresBoucle(fin_de_parole_ms=config.voix.fin_de_parole_ms,
                                                       anticipation_ms=config.voix.anticipation_ms,
                                                       ecoute_continue_s=0.5))
                boucle.declencher()
                await asyncio.wait_for(boucle.executer(), 120)
                if boucle.mesures and boucle.mesures[0].latence_ms is not None:
                    latences.append(boucle.mesures[0].latence_ms)
            resultats[cle] = round(statistics.median(latences)) if latences else None
        journal.fermer()
    resultats["note_latence"] = ("micro simulé : mesure de la fin de parole au premier son produit, sans le "
                                 "trajet acoustique ni le tampon de la carte son (~20-50 ms à ajouter)")
    return resultats


# --- Rapport --------------------------------------------------------------------------------


def comparer(actuel: dict, precedent: dict) -> list[str]:
    alertes = []
    for cle, (_, sens) in BUDGETS.items():
        a, p = actuel.get(cle), precedent.get(cle)
        if not isinstance(a, (int, float)) or not isinstance(p, (int, float)) or not p:
            continue
        variation = (a - p) / abs(p)
        if variation * sens < -SEUIL_REGRESSION:
            alertes.append(f"{cle} : {p} → {a} ({variation:+.0%}) — régression à justifier dans PLAN.md")
    return alertes


def markdown(r: dict) -> str:
    lignes = [f"# Banc Jarvis — {r['date']}", "", f"Modèle : `{r['modele']}` · llama.cpp {r['llama_cpp']} · "
              f"spéculatif : {r['speculatif']} · cache KV : {r['cache_kv']}", "", "## Budgets", "",
              "| Mesure | Valeur | Objectif | Tenu |", "|---|---|---|---|"]
    for cle, (objectif, sens) in BUDGETS.items():
        v = r.get(cle)
        tenu = "—" if v is None else ("oui" if (v <= objectif if sens < 0 else v >= objectif) else "**NON**")
        lignes.append(f"| {cle} | {v if v is not None else '—'} | {'≤' if sens < 0 else '≥'} {objectif} | {tenu} |")
    if r.get("regressions"):
        lignes += ["", "## Régressions (> 10 %)", ""] + [f"- {a}" for a in r["regressions"]]
    cmd = r.get("commandes")
    if cmd:
        lignes += ["", f"## Batterie de commandes : {cmd['reussis']}/{cmd['total']} ({cmd['taux']:.0%})", "",
                   f"Chemin rapide (sans modèle) : {cmd['chemin_rapide']} cas · durée médiane {cmd['duree_mediane_s']} s · "
                   f"{cmd['nombre_outils']} outils", ""]
        lignes += [f"- {t} : {v:.0%}" for t, v in cmd["par_tag"].items() if v is not None]
        lignes += ["", "### Échecs", ""] + [f"- `{e['id']}` : {e['motif'][:140]}" for e in cmd["echecs"]]
    notes = [v for k, v in r.items() if k.startswith("note_")]
    if notes:
        lignes += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="jarvis banc")
    p.add_argument("--commandes", action="store_true")
    p.add_argument("--perf", action="store_true")
    p.add_argument("--url", help="serveur de modèles déjà lancé (sinon : démarré avec la configuration)")
    p.add_argument("--sans-voix", action="store_true", help="ne pas mesurer PERF-01/02/07")
    p.add_argument("--sortie", type=Path, default=Path("banc-resultats"))
    args = p.parse_args(argv)
    tout = not args.commandes and not args.perf
    config = module_config.charger()
    from jarvis.diagnostic.catalogue import LLAMA_CPP_VERSION

    rapport: dict = {"date": datetime.now().isoformat(timespec="minutes"), "modele": config.llm.principal,
                     "llama_cpp": LLAMA_CPP_VERSION, "speculatif": config.llm.speculatif, "cache_kv": config.llm.cache_kv}

    async def executer() -> None:
        from jarvis.llm.serveur import Lancement, ServeurModele

        serveur = None
        if args.perf or tout:
            print("Démarrage et bascule (PERF-09, PERF-10)…", flush=True)
            try:
                rapport.update(await mesurer_demarrage_et_bascule(config))
            except Exception as e:  # noqa: BLE001
                rapport["erreur_demarrage"] = str(e)
        url = args.url or config.llm.url_externe
        if not url:
            c = config.llm
            serveur = ServeurModele()
            await serveur.demarrer(Lancement(c.principal, c.backend, c.port, c.contexte, speculatif=c.speculatif,
                                             brouillon=c.brouillon, cache_kv=c.cache_kv))
            url = serveur.url
        client = ClientLLM(url, temperature=0)
        try:
            if args.perf or tout:
                print("Génération et cache du contexte (PERF-05, PERF-06)…", flush=True)
                rapport.update(await mesurer_generation(client))
                print("Mémoire (PERF-13)…", flush=True)
                rapport.update(await asyncio.to_thread(mesurer_memoire))
                if not args.sans_voix:
                    print("CPU au repos (PERF-07)…", flush=True)
                    rapport.update(await asyncio.to_thread(mesurer_cpu_repos))
                    print("Latences vocales (PERF-01, PERF-02)…", flush=True)
                    rapport.update(await mesurer_latences_voix(client, config))
            if args.commandes or tout:
                print("Batterie de commandes (NF-02)…", flush=True)
                rapport["commandes"] = await batterie_commandes(client, config)
                rapport["NF-02_taux_commandes"] = rapport["commandes"]["taux"]
        finally:
            await client.fermer()
            if serveur:
                await serveur.arreter()

    asyncio.run(executer())
    precedents = sorted(args.sortie.glob("*/banc.json"))
    if precedents:
        rapport["regressions"] = comparer(rapport, json.loads(precedents[-1].read_text("utf-8")))
    dossier = args.sortie / datetime.now().strftime("%Y-%m-%d_%H%M")
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "banc.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2, default=str), "utf-8")
    (dossier / "banc.md").write_text(markdown(rapport), "utf-8")
    print("\n" + markdown(rapport))
    print(f"Rapport : {(dossier / 'banc.md').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
