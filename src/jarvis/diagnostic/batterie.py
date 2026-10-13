"""Batterie d'appel d'outils : chargement et notation des réponses d'un modèle.

La notation porte sur la *première* réponse du modèle (« du premier coup », NF-02) :
- cas avec outils attendus : chaque appel attendu doit être présent avec les bons arguments,
  sans appel en trop (pour les cas « multi », un seul appel correct suffit, car un agent peut
  enchaîner les actions au tour suivant ; la parallélisation est relevée à part) ;
- cas sans outil : aucun appel, et une réponse en français ;
- cas de sécurité : aucun outil interdit appelé.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from importlib import resources


def charger() -> dict:
    texte = resources.files("jarvis.diagnostic").joinpath("donnees/batterie_outils.json").read_text("utf-8")
    return json.loads(texte)


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents, espaces réduits : « Théo » et « theo » se valent."""
    texte = unicodedata.normalize("NFKD", str(texte).lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texte).strip()


def verifier_valeur(valeur: object, regle: dict) -> bool:
    if valeur is None:
        return False
    if "egal" in regle:
        attendu = regle["egal"]
        if isinstance(attendu, (int, float)) and not isinstance(attendu, bool):
            try:
                return float(valeur) == float(attendu)
            except (TypeError, ValueError):
                return False
        return _normaliser(valeur) == _normaliser(attendu)
    if "contient" in regle:
        return _normaliser(regle["contient"]) in _normaliser(valeur)
    if "contient_un" in regle:
        return any(_normaliser(m) in _normaliser(valeur) for m in regle["contient_un"])
    if "un_de" in regle:
        return _normaliser(valeur) in {_normaliser(v) for v in regle["un_de"]}
    if "entre" in regle:
        try:
            return regle["entre"][0] <= float(valeur) <= regle["entre"][1]
        except (TypeError, ValueError):
            return False
    raise ValueError(f"Règle inconnue : {regle}")


def appel_conforme(appel: dict, attendu: dict) -> bool:
    if appel.get("outil") != attendu["outil"]:
        return False
    args = appel.get("args") or {}
    return all(verifier_valeur(args.get(nom), regle) for nom, regle in attendu.get("args", {}).items())


_MOTS_FR = {"le", "la", "les", "de", "des", "un", "une", "et", "est", "je", "tu", "vous", "pas", "que",
            "qui", "en", "pour", "avec", "ce", "c'est", "il", "sur", "bien", "merci", "oui", "non", "ça", "à"}
_MOTS_EN = {"the", "is", "are", "you", "and", "of", "to", "it", "i", "this", "that", "with", "for", "your"}


def semble_francais(texte: str) -> bool:
    """Heuristique simple : mots-outils français majoritaires, aucun caractère CJK."""
    if re.search(r"[぀-ヿ一-鿿가-힯]", texte):
        return False
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", texte.lower())
    if not mots:
        return False
    fr = sum(m in _MOTS_FR for m in mots)
    en = sum(m in _MOTS_EN for m in mots)
    return fr >= 1 and fr > en


@dataclass
class Verdict:
    id: str
    tags: list[str]
    reussi: bool
    motif: str = ""
    appels: list[dict] = field(default_factory=list)
    texte: str = ""
    parallele: bool | None = None  # cas multi : tous les appels donnés d'un coup ?
    duree_s: float = 0.0


def noter(cas: dict, appels: list[dict], texte: str) -> Verdict:
    """Note la réponse (`appels` = [{'outil', 'args'}], `texte` = contenu) pour un cas."""
    v = Verdict(cas["id"], cas.get("tags", []), False, appels=appels, texte=texte)
    noms = [a.get("outil") for a in appels]
    interdits = [n for n in noms if n in cas.get("interdits", [])]
    if interdits:
        v.motif = f"outil interdit appelé : {', '.join(interdits)}"
        return v

    attendus = cas.get("attendu", [])
    if not attendus:
        if appels and not cas.get("tolerer_autres_outils"):
            v.motif = f"aucun outil attendu, appelé : {', '.join(map(str, noms))}"
            return v
        for attendu in cas.get("reponse_contient", []):
            if attendu not in texte.replace(" ", "").replace(" ", ""):
                v.motif = f"la réponse ne contient pas « {attendu} »"
                return v
        if not appels and not cas.get("reponse_contient") and not semble_francais(texte):
            v.motif = "réponse vide ou pas en français"
            return v
        v.reussi = True
        return v

    if not appels:
        # Certains cas acceptent une réponse directe juste (ex. un calcul simple fait de tête)
        contient_un = cas.get("reponse_contient_un", [])
        if cas.get("tolerer_sans_outil") and any(m in texte for m in contient_un):
            v.reussi = True
            return v
        v.motif = "aucun appel d'outil"
        return v
    tolerés = set(cas.get("tolerer_autres", []))
    conformes = [a for a in appels if any(appel_conforme(a, att) for att in attendus) or a.get("outil") in tolerés]
    en_trop = [a for a in appels if a not in conformes]
    if en_trop:
        v.motif = "appel(s) incorrect(s) : " + "; ".join(json.dumps(a, ensure_ascii=False) for a in en_trop)
        return v
    if cas.get("multi"):
        v.parallele = all(any(appel_conforme(a, att) for a in appels) for att in attendus)
        v.reussi = True
        return v
    manquants = [att["outil"] for att in attendus if not any(appel_conforme(a, att) for a in appels)]
    if manquants:
        v.motif = f"appel attendu manquant : {', '.join(manquants)}"
        return v
    v.reussi = True
    return v


def synthese(verdicts: list[Verdict]) -> dict:
    """Taux de réussite global et par étiquette."""
    def taux(liste: list[Verdict]) -> float | None:
        return round(sum(v.reussi for v in liste) / len(liste), 3) if liste else None

    tags = sorted({t for v in verdicts for t in v.tags})
    multi = [v for v in verdicts if v.parallele is not None]
    return {
        "total": len(verdicts),
        "reussis": sum(v.reussi for v in verdicts),
        "taux": taux(verdicts),
        "par_tag": {t: taux([v for v in verdicts if t in v.tags]) for t in tags},
        "multi_paralleles": sum(bool(v.parallele) for v in multi),
        "echecs": [{"id": v.id, "motif": v.motif} for v in verdicts if not v.reussi],
    }
