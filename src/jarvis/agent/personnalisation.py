"""Personnalisation sans entraînement (IA-03, solution de repli décidée en J17, D21).

L'entraînement LoRA n'est pas réalisable sur la RX 6750 XT sous Windows (voir PLAN.md, D21) :
Jarvis apprend donc de Mathieu par ses consignes. Une fois par jour, au démarrage, il choisit
dans le journal des exemples représentatifs de ses demandes réussies (outils variés) et les
ajoute aux consignes fixes, qui restent ainsi en cache le reste de la journée (PERF-06).
"""

from __future__ import annotations

import json

EXEMPLES_MAX = 12


def choisir_exemples(actions: list[dict], n: int = EXEMPLES_MAX) -> list[dict]:
    """Demandes réussies, directes (voix ou texte), une par outil, des plus récentes aux plus anciennes."""
    vus, choisis = set(), []
    for a in actions:  # plus récentes d'abord
        origine = (a.get("origine") or "").split(":")[0]
        demande = (a.get("demande") or "").strip()
        if not a.get("ok") or origine not in ("voix", "texte") or a.get("suite_contenu_externe") or not demande:
            continue
        if a["outil"] in vus or len(demande) > 160:
            continue
        vus.add(a["outil"])
        choisis.append({"demande": demande, "outil": a["outil"], "arguments": a.get("arguments") or "{}"})
        if len(choisis) >= n:
            break
    return choisis


def bloc_consignes(actions: list[dict]) -> str:
    exemples = choisir_exemples(actions)
    if len(exemples) < 3:
        return ""
    lignes = []
    for e in exemples:
        args = e["arguments"] if isinstance(e["arguments"], str) else json.dumps(e["arguments"], ensure_ascii=False)
        lignes.append(f"- « {e['demande']} » → {e['outil']} {args}")
    return ("\n\nExemples réels de demandes de Mathieu et de l'action qui lui convenait (sa façon de parler) :\n"
            + "\n".join(lignes))
