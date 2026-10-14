"""Chemin rapide (PERF-02, extensions §2.2) : les commandes très fréquentes et sans ambiguïté sont
reconnues sans le modèle de langage, puis exécutées par l'orchestrateur (permissions, journal et
vérification inchangés). Tout ce qui n'est pas reconnu avec certitude va au modèle.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

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


# --- Rappels et souvenirs : le texte libre garde ses accents ---------------------------------

_PREFIXE = re.compile(r"^\s*(h?[ée]y?\s+)?jarvis\s*[,!.]?\s*", re.I)
_POLITESSE = re.compile(r"\s*(,?\s*s'il te pla[iî]t|,?\s*stp|,?\s*merci)\s*[.!?]*$", re.I)
_RAPPEL_DANS = re.compile(r"^rappelle[- ]moi (de |d'|qu'|que )?(?P<quoi>.+?),? dans (?P<n>\d+|[a-zé\- ]+?) "
                          r"(?P<u>secondes?|minutes?|min|heures?|h)$", re.I)
_RAPPEL_A = re.compile(r"^rappelle[- ]moi (de |d'|qu'|que )?(?P<quoi>.+?),? (?P<jour>demain |ce soir |aujourd'hui )?"
                       r"(?:à|a) (?P<h>\d{1,2}) ?(?:h|heures?|:) ?(?P<m>\d{2})?$", re.I)
_RAPPEL_DEBUT = re.compile(r"^rappelle[- ]moi (?P<jour>demain |ce soir )?(?:à|a) (?P<h>\d{1,2}) ?(?:h|heures?|:) ?"
                           r"(?P<m>\d{2})? (de |d'|qu'|que )(?P<quoi>.+)$", re.I)
_RETIENS = re.compile(r"^(retiens|souviens-toi|rappelle-toi|note|n'oublie pas) (bien )?(que |qu')(?P<fait>.+)$", re.I)

# Verbes irréguliers à la 1re personne → 3e personne (« je suis » → « Mathieu est »)
_IRREGULIERS = {"suis": "est", "ai": "a", "vais": "va", "fais": "fait", "peux": "peut", "veux": "veut",
                "dois": "doit", "sais": "sait", "prends": "prend", "bois": "boit", "vis": "vit", "dors": "dort",
                "sors": "sort", "pars": "part", "finis": "finit", "lis": "lit", "écris": "écrit", "crois": "croit",
                "connais": "connaît", "mets": "met", "viens": "vient", "tiens": "tient", "préfère": "préfère"}
_POSSESSIFS = {"mon": "son", "ma": "sa", "mes": "ses", "moi": "lui"}


def _texte_libre(texte: str) -> str:
    t = _POLITESSE.sub("", _PREFIXE.sub("", texte.strip())).strip().rstrip(" .!")
    return re.sub(r"\s+", " ", t.replace("’", "'"))


def a_la_troisieme_personne(fait: str) -> str:
    """« je joue à CS2 » → « Mathieu joue à CS2 » ; formule non convertible → citation fidèle."""
    m = re.match(r"^(je |j')(?P<verbe>[\wéèêàç]+)(?P<reste>.*)$", fait, re.I)
    if not m:
        if re.search(r"\b(mon|ma|mes|moi|me|m\'|nous|notre|nos)\b", fait, re.I):
            return f"Mathieu a dit : « {fait} »"  # « mon frère s'appelle Léo » : cité tel quel
        return fait[0].upper() + fait[1:] if fait else fait
    verbe = m.group("verbe").lower()
    if verbe in ("me", "ne", "te", "le", "la", "les", "lui", "y", "en"):  # « je me lève » : citation
        return f"Mathieu a dit : « {fait} »"
    if verbe in _IRREGULIERS:
        verbe = _IRREGULIERS[verbe]
    elif not verbe.endswith("e"):  # conjugaison incertaine : on cite plutôt que d'écrire faux
        return f"Mathieu a dit : « {fait} »"
    reste = re.sub(r"\b(mon|ma|mes|moi)\b", lambda x: _POSSESSIFS[x.group(1).lower()], m.group("reste"), flags=re.I)
    if re.search(r"\b(je|j\'|me|m\')\b", reste, re.I):
        return f"Mathieu a dit : « {fait} »"
    return f"Mathieu {verbe}{reste}"


def _moment(jour: str | None, h: int, m: int, maintenant: datetime) -> datetime | None:
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    moment = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
    jour = (jour or "").strip().lower()
    if jour == "demain":
        moment += timedelta(days=1)
    elif jour == "ce soir" and h < 12:
        moment += timedelta(hours=12)  # « ce soir à 8 h » = 20 h
    elif moment <= maintenant:
        if not jour and h < 12 and (moment + timedelta(hours=12)) > maintenant:
            moment += timedelta(hours=12)  # « à 8 h » dit à 15 h : 20 h, pas demain matin
        else:
            moment += timedelta(days=1)
    return moment


def _rappel(quoi: str, moment: datetime) -> Commande:
    quoi = quoi.strip().rstrip(",")
    return Commande("creer_rappel", {"texte": quoi[0].upper() + quoi[1:], "quand": moment.isoformat(timespec="seconds")},
                    "{message}")


def reconnaitre_libre(texte: str, maintenant: datetime | None = None) -> Commande | None:
    maintenant = maintenant or datetime.now()
    t = _texte_libre(texte)
    if " puis " in t.lower() or re.search(r"\bet (lance|ouvre|mets|ferme|envoie)\b", t, re.I):
        return None
    if m := _RAPPEL_DANS.match(t):
        n = lire_nombre(m.group("n"))
        if not n:
            return None
        u = m.group("u").lower()
        secondes = n * (1 if u.startswith("s") else 3600 if u.startswith("h") else 60)
        return _rappel(m.group("quoi"), maintenant + timedelta(seconds=secondes))
    for motif in (_RAPPEL_A, _RAPPEL_DEBUT):
        if m := motif.match(t):
            moment = _moment(m.group("jour"), int(m.group("h")), int(m.group("m") or 0), maintenant)
            return _rappel(m.group("quoi"), moment) if moment else None
    if m := _RETIENS.match(t):
        fait = m.group("fait").strip()
        if len(fait) < 4 or "?" in fait:
            return None
        return Commande("memoriser", {"fait": a_la_troisieme_personne(fait)}, "C'est noté.")
    return None


def reconnaitre(texte: str, application_connue=None, routine_connue=None,
                maintenant: datetime | None = None) -> Commande | None:
    """Renvoie la commande si la phrase est reconnue avec certitude, sinon None."""
    if (libre := reconnaitre_libre(texte, maintenant)) is not None:
        return libre
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
