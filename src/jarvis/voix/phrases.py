"""Découpage du texte diffusé par le modèle en phrases à prononcer (VOX-03), et nettoyage pour la voix."""

from __future__ import annotations

import re

_FIN = re.compile(r"([.!?…]+|:\s*\n|\n\n)(\s+|$)")
_ABREVIATIONS = ("M.", "Mme.", "Dr.", "etc.", "p. ex.", "env.", "n°.")


class DecoupeurPhrases:
    """Reçoit des morceaux de texte, rend les phrases complètes dès qu'elles sont terminées."""

    def __init__(self, longueur_min: int = 12):
        self.tampon = ""
        self.longueur_min = longueur_min

    def ajouter(self, morceau: str) -> list[str]:
        self.tampon += morceau
        phrases = []
        debut = 0
        for m in _FIN.finditer(self.tampon):
            fin = m.end()
            candidate = self.tampon[debut:fin].strip()
            if len(candidate) < self.longueur_min or candidate.endswith(_ABREVIATIONS):
                continue
            # Un point entre deux chiffres (3.5) n'est pas une fin de phrase
            if m.group(1) == "." and fin < len(self.tampon) and self.tampon[m.start() - 1:m.start()].isdigit() \
                    and self.tampon[fin:fin + 1].isdigit():
                continue
            phrases.append(candidate)
            debut = fin
        self.tampon = self.tampon[debut:]
        return [p for p in (pour_la_voix(p) for p in phrases) if p]

    def vider(self) -> list[str]:
        reste = pour_la_voix(self.tampon.strip())
        self.tampon = ""
        return [reste] if reste else []


def pour_la_voix(texte: str) -> str:
    """Retire le Markdown et les symboles qui se lisent mal à voix haute."""
    texte = re.sub(r"```.*?```", " ", texte, flags=re.S)
    texte = re.sub(r"`([^`]*)`", r"\1", texte)
    texte = re.sub(r"\*\*|__|\*|#+\s*|^\s*[-•]\s+", "", texte, flags=re.M)
    texte = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texte)
    texte = re.sub(r"https?://\S+", "un lien", texte)
    texte = texte.replace("%", " pour cent").replace("&", " et ").replace("°C", " degrés")
    return re.sub(r"\s+", " ", texte).strip()
