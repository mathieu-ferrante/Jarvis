"""Étape interactive au micro : niveau de bruit ambiant, mot de réveil et phrases lues par Mathieu.

Les enregistrements restent sur le PC (dossier de résultats, exclu du dépôt). Ils servent au
test de transcription « en vrai » et au test du mot de réveil avec la voix de Mathieu.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from jarvis.diagnostic import audio


def peripheriques_entree() -> dict:
    try:
        import sounddevice as sd

        appareils = sd.query_devices()
        defaut = sd.default.device[0]
    except Exception as e:
        return {"erreur": f"{type(e).__name__} : {e}", "entrees": []}
    entrees = [{"index": i, "nom": a["name"], "taux": int(a["default_samplerate"])}
               for i, a in enumerate(appareils) if a["max_input_channels"] > 0]
    return {"defaut": defaut, "entrees": entrees}


def enregistrer(secondes: float) -> np.ndarray:
    """Enregistre au micro par défaut, renvoie du 16 kHz mono float32."""
    import sounddevice as sd

    taux = int(sd.query_devices(kind="input")["default_samplerate"])
    son = sd.rec(int(secondes * taux), samplerate=taux, channels=1, dtype="float32")
    sd.wait()
    return audio.reechantillonner(son[:, 0], taux)


def _attendre(message: str) -> None:
    input(f"\n  {message}\n  Appuyez sur Entrée quand vous êtes prêt (l'enregistrement démarre aussitôt)… ")


def etape_interactive(dossier: Path, phrases: list[str]) -> dict:
    """Déroule l'étape micro. Renvoie le relevé, les extraits pour la transcription et le réveil."""
    infos = peripheriques_entree()
    if not infos.get("entrees"):
        return {"releve": {**infos, "statut": "aucun micro détecté"}, "stt": [], "reveil": []}
    dossier.mkdir(parents=True, exist_ok=True)
    releve: dict = {**infos}

    print("\n  === Étape micro (environ 2 minutes) ===")
    print("  Parlez normalement, à votre distance habituelle du micro, comme si Jarvis tournait déjà.")
    _attendre("1/4 : silence. Ne dites rien pendant 4 secondes (bruit ambiant du PC).")
    ambiant = enregistrer(4)
    audio.ecrire_wav(dossier / "ambiant.wav", ambiant, audio.TAUX_STT)
    releve["bruit_ambiant_dbfs"] = audio.niveau_dbfs(ambiant)

    reveil = []
    for i, (consigne, attendu) in enumerate([("« Hey Jarvis »", True), ("« Hey Jarvis »", True),
                                             ("« Jarvis » (seul)", "seul"), ("« Jarvis » (seul)", "seul"),
                                             ("« J'ai joué à Valorant hier soir »", False)]):
        _attendre(f"2/4 : mot de réveil ({i + 1}/5). Dites {consigne} dans les 3 secondes.")
        son = enregistrer(3)
        chemin = audio.ecrire_wav(dossier / f"reveil-{i}.wav", son, audio.TAUX_STT)
        reveil.append({"id": f"micro-reveil-{i}", "attendu": attendu, "chemin": str(chemin)})

    stt = []
    niveaux = []
    a_lire = phrases[:5]
    for i, phrase in enumerate(a_lire):
        _attendre(f"3/4 : lecture ({i + 1}/{len(a_lire)}). Lisez à voix haute en 6 secondes :\n\n      {phrase}\n")
        son = enregistrer(6)
        niveaux.append(audio.niveau_dbfs(son))
        chemin = audio.ecrire_wav(dossier / f"phrase-{i}.wav", son, audio.TAUX_STT)
        stt.append({"id": f"micro-{i}", "texte": phrase, "chemin": str(chemin), "duree_s": 6.0})
    releve["niveau_parole_dbfs"] = round(float(np.median(niveaux)), 1)
    releve["rapport_signal_bruit_db"] = round(releve["niveau_parole_dbfs"] - releve["bruit_ambiant_dbfs"], 1)

    print("\n  4/4 : merci, l'étape micro est terminée.")
    releve["statut"] = "ok"
    return {"releve": releve, "stt": stt, "reveil": reveil}
