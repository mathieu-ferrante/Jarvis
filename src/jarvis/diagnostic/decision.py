"""Choix par la mesure : règles explicites qui transforment les chiffres du diagnostic en décisions.

Les seuils découlent du cahier des charges (NF-01 : 1,5 s de la fin de parole au premier son ;
NF-02 : 90 % de commandes réussies). Le découpage du budget de latence entre les briques est
une hypothèse de départ, révisable en J1.
"""

from __future__ import annotations

# Budget de latence NF-01 (1 500 ms), hypothèse de répartition
FIN_DE_PAROLE_MS = 400  # silence attendu par la détection de fin de parole (réglable en J1)
BUDGET_TOTAL_MS = 1500
STT_MAX_MS = 500
LLM_PREMIERE_PHRASE_MAX_MS = 700
TTS_PREMIERE_PHRASE_MAX_MS = 300

# Appel d'outils
BATTERIE_CIBLE = 0.90  # NF-02
BATTERIE_MIN = 0.80  # en dessous, le modèle est écarté même s'il est rapide
EGALITE_BATTERIE = 0.035  # un cas sur 29 : en deçà, on départage par la vitesse
GENERATION_MIN_TOK_S = 20  # plus lent que la parole : la voix rattraperait le texte
VRAM_UTILE_GO = 11.0  # sur 12 Go, en laissant de la marge au bureau Windows
EGALITE_WER = 0.02


def _lat(m: dict, cle: str) -> float:
    return (m.get("latence") or {}).get(cle) or float("inf")


def _taux(m: dict, tag: str | None = None) -> float:
    b = m.get("batterie") or {}
    if tag:
        return (b.get("par_tag") or {}).get(tag) or 0.0
    return b.get("taux") or 0.0


def _tient_en_vram(m: dict) -> bool:
    prevue = m.get("memoire_prevue_go")
    return prevue is None or prevue <= VRAM_UTILE_GO


def choisir_llm_principal(mesures: list[dict]) -> dict:
    candidats = [m for m in mesures if m.get("role") == "principal" and not m.get("cpu_seul")
                 and not m.get("erreur") and m.get("batterie")]
    # Mode --rapide : seul le petit modèle de test est mesuré, il tient lieu de principal
    candidats = candidats or [m for m in mesures if m.get("role") == "test" and not m.get("cpu_seul")
                              and not m.get("erreur") and m.get("batterie")]
    if not candidats:
        return {"choix": None, "motif": "aucun modèle principal mesuré sans erreur"}
    eligibles = [m for m in candidats
                 if _taux(m) >= BATTERIE_MIN
                 and _lat(m, "chaud_premiere_phrase_ms") <= LLM_PREMIERE_PHRASE_MAX_MS * 1.5
                 and ((m.get("latence") or {}).get("generation_tok_s") or 0) >= GENERATION_MIN_TOK_S
                 and _tient_en_vram(m)]
    provisoire = not eligibles
    pool = eligibles or candidats
    meilleur_taux = max(_taux(m) for m in pool)
    finalistes = [m for m in pool if _taux(m) >= meilleur_taux - EGALITE_BATTERIE]
    choix = min(finalistes, key=lambda m: _lat(m, "chaud_premiere_phrase_ms"))
    motif = (f"meilleur taux d'appel d'outils ({_taux(choix):.0%}) à {EGALITE_BATTERIE:.1%} près, "
             f"puis le plus rapide ({_lat(choix, 'chaud_premiere_phrase_ms'):.0f} ms jusqu'à la première phrase)")
    if provisoire:
        motif = "AUCUN modèle ne remplit tous les seuils ; choix par défaut : " + motif
    return {"choix": choix["modele"], "motif": motif, "conforme_nf02": _taux(choix) >= BATTERIE_CIBLE,
            "provisoire": provisoire}


def choisir_llm_rapide(mesures: list[dict], principal: str | None) -> dict:
    """Routage (BRN-02). Si le modèle principal est assez rapide, un seul modèle suffit."""
    par_cle = {m["modele"]: m for m in mesures if not m.get("cpu_seul")}
    p = par_cle.get(principal or "")
    if p and _lat(p, "chaud_premiere_phrase_ms") <= LLM_PREMIERE_PHRASE_MAX_MS * 0.7:
        return {"choix": principal, "motif": "le modèle principal est assez rapide : un seul modèle en VRAM"}
    candidats = [m for m in mesures if m.get("role") == "rapide" and not m.get("cpu_seul")
                 and not m.get("erreur") and m.get("batterie")]
    eligibles = [m for m in candidats if _taux(m, "simple") >= BATTERIE_CIBLE] or candidats
    if not eligibles:
        return {"choix": principal, "motif": "aucun petit modèle mesuré : le principal fait tout"}
    choix = min(eligibles, key=lambda m: _lat(m, "chaud_premiere_phrase_ms"))
    vram = (choix.get("memoire_prevue_go") or 0) + ((p or {}).get("memoire_prevue_go") or 0)
    return {"choix": choix["modele"],
            "motif": f"commandes simples réussies à {_taux(choix, 'simple'):.0%}, le plus rapide",
            "cohabitation_vram_go": round(vram, 1), "tient_avec_principal": vram <= VRAM_UTILE_GO}


def choisir_mode_jeu(mesures: list[dict]) -> dict:
    """Pendant une partie, le GPU est au jeu : modèle léger sur CPU (NF-03, VOX-07)."""
    cpu = [m for m in mesures if m.get("cpu_seul") and not m.get("erreur")]
    if not cpu:
        return {"choix": None, "motif": "pas de mesure CPU"}
    choix = max(cpu, key=lambda m: (m.get("bench") or {}).get("tg128_tok_s") or 0)
    return {"choix": choix["modele"], "generation_tok_s": (choix.get("bench") or {}).get("tg128_tok_s"),
            "premiere_phrase_ms": _lat(choix, "chaud_premiere_phrase_ms"),
            "motif": "génération la plus rapide sur CPU seul"}


def choisir_stt(mesures: list[dict]) -> dict:
    ok = [m for m in mesures if not m.get("erreur") and "latence_mediane_ms" in m]
    if not ok:
        return {"choix": None, "motif": "aucune transcription mesurée sans erreur"}

    def erreur(m: dict) -> float:
        if "wer_micro" in m:
            return m["wer_micro"]
        return 0.5 * m.get("wer_propre", 1) + 0.5 * m.get("wer_bruit", 1)

    eligibles = [m for m in ok if m["latence_mediane_ms"] <= STT_MAX_MS]
    pool = eligibles or ok
    meilleure = min(erreur(m) for m in pool)
    finalistes = [m for m in pool if erreur(m) <= meilleure + EGALITE_WER]
    choix = min(finalistes, key=lambda m: m["latence_mediane_ms"])
    base = "voix réelle de Mathieu" if "wer_micro" in choix else "voix de synthèse (propre + bruit)"
    return {"choix": f"{choix['modele']} ({choix.get('variante', 'cpu')})",
            "motif": f"WER {erreur(choix):.1%} sur {base} à {EGALITE_WER:.0%} près, "
                     f"puis le plus rapide ({choix['latence_mediane_ms']} ms)",
            "latence_ms": choix["latence_mediane_ms"], "provisoire": not eligibles}


def choisir_tts(mesures: list[dict]) -> dict:
    ok = [m for m in mesures if not m.get("erreur")]
    if not ok:
        return {"choix": None, "motif": "aucune voix mesurée sans erreur"}
    eligibles = [m for m in ok if m["premiere_phrase_ms"] <= TTS_PREMIERE_PHRASE_MAX_MS]
    # À latence acceptable, Kokoro est réputé plus naturel que Piper : à confirmer à l'oreille.
    kokoro = [m for m in eligibles if m["moteur"] == "kokoro"]
    pool = kokoro or eligibles or ok
    choix = min(pool, key=lambda m: m["premiere_phrase_ms"])
    return {"choix": choix["voix"], "latence_ms": choix["premiere_phrase_ms"],
            "motif": "la plus rapide parmi les voix sous le seuil, Kokoro de préférence ; "
                     "PROVISOIRE : le choix final se fait à l'oreille (A_VALIDER.md)",
            "provisoire": True}


def budget_latence(stt_ms: float | None, llm_ms: float | None, tts_ms: float | None) -> dict:
    """Estimation NF-01 : fin de parole → premier son, en additionnant les briques mesurées."""
    if None in (stt_ms, llm_ms, tts_ms) or float("inf") in (stt_ms, llm_ms, tts_ms):
        return {"estimation_ms": None, "motif": "briques manquantes"}
    total = FIN_DE_PAROLE_MS + stt_ms + llm_ms + tts_ms
    return {
        "fin_de_parole_ms": FIN_DE_PAROLE_MS, "transcription_ms": stt_ms,
        "premiere_phrase_llm_ms": llm_ms, "premiere_phrase_voix_ms": tts_ms,
        "estimation_ms": round(total), "objectif_ms": BUDGET_TOTAL_MS, "tenu": total <= BUDGET_TOTAL_MS,
    }


def decider(resultats: dict) -> dict:
    llm = resultats.get("llm", [])
    principal = choisir_llm_principal(llm)
    rapide = choisir_llm_rapide(llm, principal.get("choix"))
    stt = choisir_stt(resultats.get("stt", []))
    tts = choisir_tts(resultats.get("tts", []))
    par_cle = {m["modele"]: m for m in llm if not m.get("cpu_seul")}
    llm_ms = _lat(par_cle.get(rapide.get("choix") or "", {}), "chaud_premiere_phrase_ms")
    return {
        "llm_principal": principal,
        "llm_rapide": rapide,
        "mode_jeu": choisir_mode_jeu(llm),
        "transcription": stt,
        "voix": tts,
        "budget_latence": budget_latence(stt.get("latence_ms"), llm_ms, tts.get("latence_ms")),
    }
