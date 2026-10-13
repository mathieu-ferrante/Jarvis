"""OUT-REM : rappels datés, récurrents, et minuteurs."""

from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.agent.contexte import date_fr
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat
from jarvis.rappels import RECURRENCES, lire_date


def _service(ctx: Contexte):
    service = ctx.services.get("rappels")
    if service is None:
        raise RuntimeError("service de rappels indisponible")
    return service


class CreerRappel(Outil):
    nom = "creer_rappel"
    description = "Crée un rappel à une date et une heure précises, éventuellement récurrent (« tous les lundis »)."
    parametres = {"type": "object", "properties": {
        "texte": {"type": "string", "description": "Ce qu'il faut rappeler."},
        "quand": {"type": "string", "description": "Date et heure ISO 8601, ex. 2026-10-13T18:30:00."},
        "recurrence": {"type": "string", "enum": list(RECURRENCES)}},
        "required": ["texte", "quand"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"créer un rappel « {args.get('texte')} » pour {args.get('quand')}"

    async def executer(self, ctx: Contexte, texte: str, quand: str, recurrence: str = "aucune") -> Resultat:
        try:
            moment = lire_date(quand)
        except ValueError:
            return Resultat.echec(f"Date illisible : {quand}. Format attendu : AAAA-MM-JJTHH:MM:SS.")
        if moment < datetime.now() - timedelta(minutes=1) and recurrence == "aucune":
            return Resultat.echec(f"Cette date est passée ({date_fr(moment)}).")
        ident = _service(ctx).ajouter(texte, moment, recurrence)
        suite = "" if recurrence == "aucune" else f", récurrence {recurrence}"
        return Resultat(True, f"Rappel n° {ident} : « {texte} » le {date_fr(moment)}{suite}.", donnees={"id": ident})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return any(r["id"] == resultat.donnees["id"] for r in _service(ctx).lister())


class CreerMinuteur(Outil):
    nom = "creer_minuteur"
    description = "Démarre un minuteur."
    parametres = {"type": "object", "properties": {
        "duree_secondes": {"type": "integer", "description": "Durée en secondes."},
        "libelle": {"type": "string"}}, "required": ["duree_secondes"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        minutes, secondes = divmod(int(args.get("duree_secondes", 0)), 60)
        return f"lancer un minuteur de {minutes} min {secondes:02d} s" if minutes else f"lancer un minuteur de {secondes} s"

    async def executer(self, ctx: Contexte, duree_secondes: int, libelle: str = "") -> Resultat:
        if duree_secondes <= 0 or duree_secondes > 7 * 86400:
            return Resultat.echec("Durée invalide.")
        fin = datetime.now() + timedelta(seconds=duree_secondes)
        ident = _service(ctx).ajouter(libelle or "Minuteur terminé", fin, type_="minuteur")
        return Resultat(True, f"Minuteur n° {ident} jusqu'à {fin.strftime('%H:%M:%S')}.", donnees={"id": ident})


class ListerRappels(Outil):
    nom = "lister_rappels"
    description = "Liste les rappels et minuteurs à venir."

    async def executer(self, ctx: Contexte) -> Resultat:
        rappels = _service(ctx).lister()
        if not rappels:
            return Resultat(True, "Aucun rappel prévu.", donnees=[])
        return Resultat(True, " ; ".join(
            f"n° {r['id']} {r['type']} « {r['texte']} » le {date_fr(lire_date(r['quand']))}"
            + ("" if r["recurrence"] == "aucune" else f" ({r['recurrence']})") for r in rappels), donnees=rappels)


class AnnulerRappel(Outil):
    nom = "annuler_rappel"
    description = "Annule un rappel ou un minuteur par son numéro."
    parametres = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    niveau = Niveau.REVERSIBLE

    async def executer(self, ctx: Contexte, id: int) -> Resultat:  # noqa: A002
        if _service(ctx).annuler(id):
            return Resultat(True, f"Rappel n° {id} annulé.")
        return Resultat.echec(f"Aucun rappel actif n° {id}.")


OUTILS = [CreerRappel, CreerMinuteur, ListerRappels, AnnulerRappel]


class CreerRappelContextuel(Outil):
    nom = "creer_rappel_contextuel"
    description = ("Crée un rappel déclenché par le contexte : en arrivant à un lieu (« quand je passe à la "
                   "boulangerie de la rue X », « ici » = position actuelle du téléphone), en utilisant un appareil "
                   "(« quand je suis sur le Mac »), ou à la fin d'une partie (« après ma partie »).")
    parametres = {"type": "object", "properties": {
        "texte": {"type": "string"},
        "declencheur": {"type": "string", "enum": ["lieu", "appareil", "fin_partie"]},
        "lieu": {"type": "string", "description": "Adresse ou nom du lieu, ou « ici »."},
        "appareil": {"type": "string", "description": "Nom de l'appareil (Mac, téléphone)."},
        "recurrent": {"type": "boolean", "description": "À chaque fois (sinon une seule fois)."}},
        "required": ["texte", "declencheur"]}
    niveau = Niveau.REVERSIBLE
    hotes = ("nominatim.openstreetmap.org",)

    def decrire(self, args):
        cible = args.get("lieu") or args.get("appareil") or "la fin de la partie"
        return f"créer un rappel « {args.get('texte')} » ({args.get('declencheur')} : {cible})"

    async def executer(self, ctx: Contexte, texte: str, declencheur: str, lieu: str = "", appareil: str = "",
                       recurrent: bool = False) -> Resultat:
        service = ctx.services.get("rappels_contexte")
        if service is None:
            return Resultat.echec("Rappels contextuels indisponibles.")
        condition: dict = {}
        if declencheur == "lieu":
            if not lieu:
                return Resultat.echec("Quel lieu ? (adresse, nom, ou « ici »)")
            if lieu.strip().lower() in ("ici", "là", "la"):
                position = await position_du_telephone(ctx)
                if not position:
                    return Resultat.echec("Position du téléphone indisponible (partage de position désactivé ?).")
                condition = {"lat": position[0], "lon": position[1], "rayon_m": 150, "nom": "l'endroit où tu étais"}
            else:
                r = await ctx.http("GET", "https://nominatim.openstreetmap.org/search",
                                   params={"q": lieu, "format": "json", "limit": 1, "accept-language": "fr"},
                                   headers={"User-Agent": "Jarvis-assistant-personnel/0.1 (usage prive)"})
                resultats = r.json() if r.status_code == 200 else []
                if not resultats:
                    return Resultat.echec(f"Lieu introuvable : {lieu}. Donne une adresse plus précise.")
                condition = {"lat": float(resultats[0]["lat"]), "lon": float(resultats[0]["lon"]), "rayon_m": 150,
                             "nom": lieu}
        elif declencheur == "appareil":
            if not appareil:
                return Resultat.echec("Sur quel appareil ?")
            condition = {"appareil": appareil}
        ident = service.ajouter(texte, declencheur, condition, recurrent)
        return Resultat(True, f"Rappel contextuel n° {ident} créé : « {texte} » ({declencheur}"
                              f"{' : ' + (lieu or appareil) if lieu or appareil else ''}).", donnees={"id": ident})


async def position_du_telephone(ctx: Contexte) -> tuple[float, float] | None:
    """Demande sa position au téléphone appairé (outil distant « position », s'il est autorisé)."""
    from jarvis.contexte_rappels import lire_position

    registre = getattr(ctx.services.get("orchestrateur"), "registre", None)
    outil = next((o for n, o in (registre.outils.items() if registre else []) if n.endswith("_position")), None)
    if outil is None:
        return None
    r = await outil.executer(ctx)
    return lire_position(r.message) if r.ok else None


OUTILS.append(CreerRappelContextuel)
