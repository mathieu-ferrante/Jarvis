"""Rapport du diagnostic : JSON complet (pour l'analyse) et Markdown lisible (pour Mathieu)."""

from __future__ import annotations

import json
import math
from pathlib import Path


def _propre(valeur):
    """Remplace les infinis et NaN (non JSON) par None, récursivement."""
    if isinstance(valeur, float) and (math.isinf(valeur) or math.isnan(valeur)):
        return None
    if isinstance(valeur, dict):
        return {k: _propre(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_propre(v) for v in valeur]
    if isinstance(valeur, Path):
        return str(valeur)
    return valeur


def ecrire_json(resultats: dict, chemin: Path) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(_propre(resultats), ensure_ascii=False, indent=2), "utf-8")
    return chemin


def _v(valeur, suffixe: str = "", defaut: str = "—") -> str:
    if valeur is None or (isinstance(valeur, float) and (math.isinf(valeur) or math.isnan(valeur))):
        return defaut
    if isinstance(valeur, float) and valeur < 1 and suffixe == "%":
        return f"{valeur:.0%}"
    return f"{valeur}{suffixe}"


def _table(entetes: list[str], lignes: list[list]) -> str:
    sortie = ["| " + " | ".join(entetes) + " |", "|" + "|".join("---" for _ in entetes) + "|"]
    sortie += ["| " + " | ".join(str(c) for c in ligne) + " |" for ligne in lignes]
    return "\n".join(sortie)


def markdown(resultats: dict) -> str:
    s = resultats.get("systeme", {})
    d = resultats.get("decisions", {})
    lignes = [
        f"# Diagnostic Jarvis — {resultats.get('date', '')}",
        "",
        f"Mode : **{'rapide (poste de développement)' if resultats.get('rapide') else 'complet'}** · "
        f"durée : {resultats.get('duree_min', '?')} min · llama.cpp {resultats.get('llama_cpp', '')}",
        "",
        "## Matériel",
        "",
        f"- CPU : {s.get('cpu')} ({s.get('coeurs_physiques')} cœurs / {s.get('coeurs_logiques')} threads)",
        f"- RAM : {s.get('ram_go')} Go",
        *[f"- GPU : {g.get('nom')} (pilote {g.get('pilote')})" for g in s.get("gpus", [])],
        *[f"- llama.cpp voit : `{p}`" for p in resultats.get("peripheriques", {}).get("vulkan", [])],
        f"- OS : {s.get('os')}",
        "",
        "## Décisions (choix par la mesure)",
        "",
    ]
    noms = {"llm_principal": "Modèle principal", "llm_rapide": "Modèle rapide (routage)",
            "mode_jeu": "Mode jeu (CPU)", "transcription": "Transcription", "voix": "Voix"}
    for cle, nom in noms.items():
        dec = d.get(cle) or {}
        lignes.append(f"- **{nom}** : `{dec.get('choix')}` — {dec.get('motif', '')}")
    b = d.get("budget_latence") or {}
    if b.get("estimation_ms") is not None:
        lignes += [
            "",
            f"**Latence estimée (NF-01)** : {b['estimation_ms']} ms pour un objectif de {b['objectif_ms']} ms "
            f"→ {'tenu' if b['tenu'] else 'NON TENU'} "
            f"(fin de parole {b['fin_de_parole_ms']} + transcription {b['transcription_ms']} + "
            f"modèle {b['premiere_phrase_llm_ms']} + voix {b['premiere_phrase_voix_ms']} ms).",
        ]

    llm = resultats.get("llm", [])
    if llm:
        lignes += ["", "## Modèles de langage", ""]
        rangs = []
        for m in llm:
            lat = m.get("latence") or {}
            bat = m.get("batterie") or {}
            bench = m.get("bench") or {}
            rangs.append([
                m.get("nom"), "CPU" if m.get("cpu_seul") else "GPU",
                _v(bench.get("pp512_tok_s")), _v(bench.get("tg128_tok_s")),
                _v(lat.get("chaud_premier_jeton_ms")), _v(lat.get("chaud_premiere_phrase_ms")),
                _v(bat.get("taux"), "%"), _v((bat.get("par_tag") or {}).get("simple"), "%"),
                _v((bat.get("par_tag") or {}).get("securite"), "%"),
                _v(m.get("memoire_prevue_go"), " Go"),
                "oui" if (m.get("vision") or {}).get("reussi") else ("non" if m.get("vision") else "—"),
                m.get("erreur", "")[:60] if m.get("erreur") else "",
            ])
        lignes.append(_table(["Modèle", "Sur", "Prompt (tok/s)", "Génération (tok/s)", "1er jeton (ms)",
                              "1re phrase (ms)", "Outils", "Simples", "Sécurité", "Mémoire", "Vision",
                              "Erreur"], rangs))
        lignes += ["", "### Échecs de la batterie d'outils", ""]
        for m in llm:
            echecs = (m.get("batterie") or {}).get("echecs")
            if echecs:
                lignes.append(f"- **{m.get('nom')}** : " + " ; ".join(f"`{e['id']}` ({e['motif'][:90]})"
                                                                    for e in echecs))
        lignes += ["", "### Français : réponses à relire", ""]
        for m in llm:
            for ex in (m.get("francais") or [])[:2]:
                lignes += [f"**{m.get('nom')}** — *{ex['question']}*", "", "> " +
                           ex["reponse"].replace("\n", "\n> "), ""]

    stt = resultats.get("stt", [])
    if stt:
        lignes += ["", "## Transcription", ""]
        lignes.append(_table(
            ["Modèle", "Variante", "Latence médiane (ms)", "Max (ms)", "WER propre", "WER bruit", "WER micro",
             "Temps réel", "Erreur"],
            [[m.get("modele"), m.get("variante"), _v(m.get("latence_mediane_ms")), _v(m.get("latence_max_ms")),
              _v(m.get("wer_propre"), "%"), _v(m.get("wer_bruit"), "%"), _v(m.get("wer_micro"), "%"),
              _v(m.get("facteur_temps_reel")), (m.get("erreur") or "")[:60]] for m in stt]))

    tts = resultats.get("tts", [])
    if tts:
        lignes += ["", "## Voix de synthèse", ""]
        lignes.append(_table(
            ["Voix", "1re phrase (ms)", "Max (ms)", "Temps réel", "Fichier à écouter", "Erreur"],
            [[m.get("voix"), _v(m.get("premiere_phrase_ms")), _v(m.get("premiere_phrase_max_ms")),
              _v(m.get("facteur_temps_reel")), Path(m["fichier_ecoute"]).name if m.get("fichier_ecoute") else "",
              (m.get("erreur") or "")[:60]] for m in tts]))

    r = resultats.get("reveil") or {}
    if r:
        lignes += ["", "## Mot de réveil", ""]
        if r.get("erreur"):
            lignes.append(f"Erreur : {r['erreur']}")
        else:
            lignes += [
                f"- Modèle : {r.get('modele')}, seuil {r.get('seuil')}",
                f"- CPU : {r['cpu']['pct_cpu_total']} % du processeur ({r['cpu']['pct_d_un_coeur']} % d'un cœur)",
                f"- « Hey Jarvis » synthétique détecté : {r.get('synthese_hey_jarvis_detectes')}",
                f"- « Jarvis » seul synthétique détecté : {r.get('synthese_jarvis_seul_detectes')}",
                f"- Faux déclenchements (phrases sans le mot) : {r.get('synthese_faux_declenchements')}"
                f" (score maximal {r.get('score_max_faux')})",
                f"- Contrôle avec voix anglaises : {r.get('controle_voix_anglaises_detectes', '—')}",
            ]
            for e in r.get("micro", []):
                lignes.append(f"- Micro `{e['id']}` (attendu : {e['attendu']}) : score {e['score']}")

    m = (resultats.get("micro") or {})
    if m:
        lignes += ["", "## Micro", "",
                   f"- Statut : {m.get('statut')}",
                   f"- Bruit ambiant : {_v(m.get('bruit_ambiant_dbfs'), ' dBFS')}, parole : "
                   f"{_v(m.get('niveau_parole_dbfs'), ' dBFS')}, rapport signal/bruit : "
                   f"{_v(m.get('rapport_signal_bruit_db'), ' dB')}"]

    if resultats.get("erreurs"):
        lignes += ["", "## Erreurs", ""] + [f"- {e}" for e in resultats["erreurs"]]
    return "\n".join(lignes) + "\n"


def ecrire_markdown(resultats: dict, chemin: Path) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(markdown(_propre(resultats)), "utf-8")
    return chemin
