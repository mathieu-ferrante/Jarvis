"""MULTI-04 : outils entre appareils (envoyer un fichier, un lien, un texte ; faire sonner)."""

from __future__ import annotations

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

SYNONYMES = {
    "telephone": (("téléphone", "telephone", "portable", "mobile", "poco", "android"), "android"),
    "mac": (("mac", "macbook", "ordinateur portable"), "mac"),
}


def trouver_appareil(appareils: list[dict], nom: str) -> dict | None:
    """Par nom (« POCO », « Téléphone »), identifiant, ou synonyme (« mon portable » → l'appareil Android)."""
    n = nom.lower().strip()
    for a in appareils:
        if n == a["id"] or n in a["nom"].lower() or a["nom"].lower() in n:
            return a
    for mots, type_ in SYNONYMES.values():
        if any(m in n for m in mots):
            for a in appareils:
                if a.get("type") == type_ or any(m in a["nom"].lower() for m in mots):
                    return a
    return None


class EnvoyerVersAppareil(Outil):
    nom = "envoyer_vers_appareil"
    description = ("Envoie sur un autre appareil de Mathieu (téléphone, Mac) un fichier du PC, un lien à ouvrir ou un "
                   "texte, ou le fait sonner pour le retrouver.")
    parametres = {"type": "object", "properties": {
        "appareil": {"type": "string", "description": "« téléphone », « Mac » ou le nom de l'appareil."},
        "type": {"type": "string", "enum": ["fichier", "lien", "texte", "sonner"]},
        "contenu": {"type": "string", "description": "Chemin du fichier, adresse du lien ou texte."}},
        "required": ["appareil", "type"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"envoyer {args.get('type')} {args.get('contenu', '')} vers {args.get('appareil')}".strip()

    async def executer(self, ctx: Contexte, appareil: str, type: str, contenu: str = "") -> Resultat:  # noqa: A002
        multi = ctx.services.get("multi")
        appareils = ctx.services.get("appareils")
        cible = trouver_appareil(appareils.lister(), appareil) if appareils else None
        if multi is None or cible is None:
            return Resultat.echec(f"Appareil « {appareil} » inconnu ou non appairé.")
        if cible["id"] not in multi.connexions:
            return Resultat.echec(f"{cible['nom']} n'est pas connecté en ce moment.")
        message: dict = {"type": "recevoir", "donnees": {"nature": type}}
        if type == "fichier":
            from jarvis.outils.fichiers import resoudre

            p = resoudre(contenu)
            if not p.is_file():
                return Resultat.echec(f"{p} introuvable.")
            message["donnees"].update(nom=p.name, url=multi.lien_fichier(p), taille=p.stat().st_size)
        elif type in ("lien", "texte"):
            message["donnees"]["contenu"] = contenu
        await multi.envoyer(cible["id"], message)
        return Resultat(True, f"Envoyé à {cible['nom']} ({type}).")


OUTILS = [EnvoyerVersAppareil]
