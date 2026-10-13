"""Routage (BRN-02) : modèle rapide pour les commandes simples, modèle capable pour le reste."""

from __future__ import annotations

import re

_VERBES_SIMPLES = (
    "baisse", "monte", "mets", "met", "coupe", "lance", "ouvre", "ferme", "pause", "reprends", "joue",
    "passe", "suivant", "suivante", "précédent", "active", "désactive", "allume", "éteins", "règle",
    "minuteur", "rappelle", "quelle heure", "volume", "stop", "arrête",
)
_COMPLEXES = re.compile(
    r"\b(pourquoi|comment|explique|résume|résumer|compare|analyse|planifie|organise|rédige|écris|"
    r"cherche|recherche|trouve|réfléchis|prépare|aide-moi|que penses|qu'est-ce qui|plusieurs|puis|ensuite)\b",
    re.I,
)


def est_simple(texte: str) -> bool:
    t = texte.lower().strip()
    if len(t.split()) > 12 or _COMPLEXES.search(t):
        return False
    return any(t.startswith(v) or f" {v}" in t for v in _VERBES_SIMPLES)


def choisir(texte: str, rapide, principal):
    """Renvoie le client à utiliser."""
    if rapide is None or rapide is principal:
        return principal
    return rapide if est_simple(texte) else principal


_REFLEXION = re.compile(
    r"\b(pourquoi|explique|analyse|compare|planifie|organise|stratégie|conseille|aide-moi à|réfléchis|"
    r"démontre|calcule|résous|prépare|rédige|que penses|quelle est la meilleure|comment (faire|améliorer|optimiser)|"
    r"débrief|progresser|programme|plan)\b", re.I)


def besoin_reflexion(texte: str, mode: str = "auto") -> bool:
    """Réflexion approfondie (plus lente, plus juste) pour les demandes qui la méritent."""
    if mode == "toujours":
        return True
    if mode == "jamais" or est_simple(texte):
        return False
    return bool(_REFLEXION.search(texte)) or len(texte.split()) > 30
