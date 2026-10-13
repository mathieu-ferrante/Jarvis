"""Habitudes (IA-04) : actions répétées détectées dans le journal, proposées avant d'être retenues.

Une habitude = la même action (outil + arguments) réussie au moins 3 jours différents sur les
14 derniers, à une heure proche (± 1 h). Jarvis la propose (« Tu lances souvent Spotify vers
21 h, je le retiens ? ») ; elle n'entre en mémoire que si Mathieu accepte.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta

OUTILS_SUIVIS = {"lancer_application", "fermer_application", "jouer_musique", "lancer_routine", "regler_volume",
                 "sortie_audio", "regler_luminosite", "commander_maison", "creer_minuteur", "statistiques_jeu"}
JOURS_MIN = 3
FENETRE_JOURS = 14

LIBELLES = {"lancer_application": "lance {nom}", "fermer_application": "ferme {nom}", "jouer_musique": "écoute {recherche}",
            "lancer_routine": "active la routine {nom}", "regler_volume": "règle le volume à {niveau} %",
            "sortie_audio": "passe le son sur {nom}", "regler_luminosite": "règle la luminosité à {niveau} %",
            "commander_maison": "demande « {action} {appareil} »", "creer_minuteur": "lance un minuteur de {duree_secondes} s",
            "statistiques_jeu": "consulte ses statistiques de {jeu}"}


def _heure_moyenne(minutes: list[int]) -> tuple[int, int]:
    """Moyenne circulaire (23 h 50 et 0 h 10 sont proches) et dispersion maximale, en minutes."""
    import math

    angles = [m / 1440 * 2 * math.pi for m in minutes]
    moyenne = math.atan2(sum(map(math.sin, angles)), sum(map(math.cos, angles))) % (2 * math.pi)
    centre = round(moyenne / (2 * math.pi) * 1440) % 1440
    ecart = max(min(abs(m - centre), 1440 - abs(m - centre)) for m in minutes)
    return centre, ecart


def detecter(actions: list[dict], maintenant: datetime | None = None) -> list[dict]:
    maintenant = maintenant or datetime.now()
    limite = maintenant - timedelta(days=FENETRE_JOURS)
    groupes: dict[tuple, list[datetime]] = defaultdict(list)
    for a in actions:
        if a.get("outil") not in OUTILS_SUIVIS or not a.get("ok"):
            continue
        quand = datetime.fromisoformat(a["horodatage"])
        if quand < limite:
            continue
        args = json.loads(a["arguments"]) if isinstance(a.get("arguments"), str) else (a.get("arguments") or {})
        cle = (a["outil"], json.dumps({k: str(v).lower() for k, v in sorted(args.items())}, ensure_ascii=False))
        groupes[cle].append(quand)
    habitudes = []
    for (outil, args_json), moments in groupes.items():
        jours = {m.date() for m in moments}
        if len(jours) < JOURS_MIN:
            continue
        par_jour = [min(m for m in moments if m.date() == j) for j in jours]  # 1re fois de chaque jour
        centre, ecart = _heure_moyenne([m.hour * 60 + m.minute for m in par_jour])
        if ecart > 60:
            continue
        args = json.loads(args_json)
        try:
            action = LIBELLES[outil].format(**args)
        except KeyError:
            action = f"utilise {outil}"
        heure = f"{centre // 60} h {centre % 60:02d}" if centre % 60 else f"{centre // 60} h"
        habitudes.append({"outil": outil, "arguments": args, "jours": len(jours), "heure": heure,
                          "texte": f"Mathieu {action} vers {heure} ({len(jours)} jours sur les {FENETRE_JOURS} derniers)"})
    return sorted(habitudes, key=lambda h: -h["jours"])


def proposer_habitudes(journal, memoire, bus=None) -> list[int]:
    proposees = []
    for h in detecter(journal.dernieres(2000)):
        ident = memoire.proposer(h["texte"], "habitude")
        if ident is not None:
            proposees.append(ident)
            if bus:
                bus.publier("proposition_souvenir", texte=h["texte"], id=ident, origine="habitude")
    return proposees
