"""Chemin rapide (PERF-02, extensions §2.2) : les commandes très fréquentes et sans ambiguïté sont
reconnues sans le modèle de langage, puis exécutées par l'orchestrateur (permissions, journal et
vérification inchangés). Tout ce qui n'est pas reconnu avec certitude va au modèle.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

NOMBRES = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
    "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20,
    "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "soixante-dix": 70, "quatre-vingt": 80,
    "quatre-vingts": 80, "quatre-vingt-dix": 90, "cent": 100,
}


def _sans_accents(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in texte if not unicodedata.combining(c))


def lire_nombre(texte: str) -> int | None:
    """« 30 », « trente », « vingt-cinq », « soixante-dix-huit »."""
    texte = texte.strip().lower().replace(" et ", "-").replace(" ", "-")
    if texte.isdigit():
        return int(texte)
    if texte in NOMBRES:
        return NOMBRES[texte]
    total, morceaux = 0, texte.split("-")
    i = 0
    while i < len(morceaux):
        # « quatre-vingt », « soixante-dix » sont des composés à deux mots
        double = "-".join(morceaux[i:i + 2])
        triple = "-".join(morceaux[i:i + 3])
        if triple in NOMBRES:
            total += NOMBRES[triple]
            i += 3
        elif double in NOMBRES:
            total += NOMBRES[double]
            i += 2
        elif morceaux[i] in NOMBRES:
            total += NOMBRES[morceaux[i]]
            i += 1
        else:
            return None
    return total or None


@dataclass
class Commande:
    outil: str
    args: dict
    gabarit: str  # réponse si succès ; {message} = message de l'outil


_NB = r"(\d+|[a-zé\- ]+?)"
_RE = [
    (re.compile(rf"^(mets|met|regle|règle) (le )?(son|volume) a {_NB}( %| pour ?cent)?$"), "volume_niveau"),
    (re.compile(rf"^(monte|augmente) (un peu )?(le )?(son|volume)( de {_NB}( %| pour ?cent| points?)?)?$"), "volume_plus"),
    (re.compile(rf"^(baisse|diminue) (un peu )?(le )?(son|volume)( de {_NB}( %| pour ?cent| points?)?)?$"), "volume_moins"),
    (re.compile(r"^(coupe le son|mute|silence radio|mets en sourdine)$"), "muet"),
    (re.compile(r"^(remets|retablis) le son$"), "son"),
    (re.compile(r"^(pause|mets (la musique )?en pause|stop la musique|arrete la musique|coupe la musique)$"), "pause"),
    (re.compile(r"^(reprends|reprend|play|relance la musique|remets la musique|reprends la musique|lecture)$"), "lecture"),
    (re.compile(r"^(suivant|suivante|chanson suivante|morceau suivant|titre suivant|passe|next|passe a la suivante)$"), "suivant"),
    (re.compile(r"^(precedent|precedente|chanson precedente|morceau precedent|titre precedent)$"), "precedent"),
    (re.compile(rf"^(mets|met|lance|demarre|programme) (moi )?un minuteur (de|d') ?{_NB} (secondes?|minutes?|heures?)( pour (.+))?$"), "minuteur"),
    (re.compile(r"^(mets|met|lance) (moi )?un minuteur (d'une demi-heure|d'un quart d'heure)( pour (.+))?$"), "minuteur_fraction"),
    (re.compile(r"^(quelle heure (est-il|il est)|il est quelle heure|l'heure)$"), "heure"),
    (re.compile(r"^(lance|ouvre|demarre) ([\w' .+-]{2,30})$"), "lancer"),
    (re.compile(r"^(ferme|quitte) ([\w' .+-]{2,30})$"), "fermer"),
    (re.compile(r"^(active|lance|demarre) (le )?mode ([\w -]{2,20})$"), "routine"),
]
_UNITES = {"seconde": 1, "minute": 60, "heure": 3600}


def normaliser(texte: str) -> str:
    t = texte.strip()
    t = re.sub(r"^(h?[ée]y?\s+)?jarvis\s*[,!.]?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*(,?\s*s'il te pla[iî]t|,?\s*stp|,?\s*merci)\s*[.!?]*$", "", t, flags=re.I)
    t = _sans_accents(t).rstrip(" .!?")
    t = t.replace("’", "'")
    return re.sub(r"\s+", " ", t)


def reconnaitre(texte: str, application_connue=None, routine_connue=None) -> Commande | None:
    """Renvoie la commande si la phrase est reconnue avec certitude, sinon None."""
    t = normaliser(texte)
    if not t or " et " in t or " puis " in t:  # plusieurs actions : au modèle
        return None
    for motif, type_ in _RE:
        m = motif.match(t)
        if not m:
            continue
        if type_ == "volume_niveau":
            n = lire_nombre(m.group(4))
            return Commande("regler_volume", {"niveau": n}, f"Volume à {n} %.") if n is not None and n <= 100 else None
        if type_ in ("volume_plus", "volume_moins"):
            n = lire_nombre(m.group(6)) if m.group(6) else 10
            if n is None:
                return None
            signe = 1 if type_ == "volume_plus" else -1
            return Commande("regler_volume", {"variation": signe * n}, "{message}")
        if type_ == "muet":
            return Commande("regler_volume", {"muet": True}, "Son coupé.")
        if type_ == "son":
            return Commande("regler_volume", {"muet": False}, "Son rétabli.")
        if type_ in ("pause", "lecture", "suivant", "precedent"):
            reponses = {"pause": "En pause.", "lecture": "C'est reparti.", "suivant": "Morceau suivant.",
                        "precedent": "Morceau précédent."}
            return Commande("controle_media", {"action": type_}, reponses[type_])
        if type_ == "minuteur":
            n = lire_nombre(m.group(4))
            if not n:
                return None
            unite = next(v for k, v in _UNITES.items() if m.group(5).startswith(k))
            libelle = (m.group(7) or "").strip()
            args = {"duree_secondes": n * unite, **({"libelle": libelle} if libelle else {})}
            return Commande("creer_minuteur", args, f"Minuteur de {n} {m.group(5)} lancé.")
        if type_ == "minuteur_fraction":
            secondes = 1800 if "demi" in m.group(3) else 900
            libelle = (m.group(5) or "").strip()
            args = {"duree_secondes": secondes, **({"libelle": libelle} if libelle else {})}
            return Commande("creer_minuteur", args, "Minuteur lancé.")
        if type_ == "heure":
            return Commande("date_et_heure", {}, "{message}")
        if type_ in ("lancer", "fermer"):
            nom = m.group(2).strip()
            if nom.startswith(("le fichier", "la page", "un ", "une ", "le dossier", "mes ", "ma ", "mon ")):
                return None
            if application_connue is None or not application_connue(nom):
                return None
            if type_ == "lancer":
                return Commande("lancer_application", {"nom": nom}, f"Je lance {nom}.")
            return Commande("fermer_application", {"nom": nom}, f"{nom.capitalize()} fermé.")
        if type_ == "routine":
            nom = m.group(3).strip()
            if routine_connue is None or not routine_connue(f"mode {nom}"):
                return None
            return Commande("lancer_routine", {"nom": f"mode {nom}"}, f"Mode {nom} activé.")
    return None
