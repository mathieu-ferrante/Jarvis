"""Outils du cœur : tâches de fond, journal des actions, heure."""

from __future__ import annotations

from datetime import datetime

from jarvis.agent.contexte import JOURS, MOIS
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat


class LancerTacheDeFond(Outil):
    nom = "lancer_tache_de_fond"
    description = ("Lance une tâche longue en arrière-plan (recherche approfondie, traitement de nombreux fichiers). "
                   "Mathieu est notifié à la fin avec le résultat.")
    parametres = {"type": "object", "properties": {"objectif": {"type": "string", "description": "Ce qu'il faut faire, précisément."}},
                  "required": ["objectif"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"lancer en arrière-plan : {args.get('objectif', '')}"

    async def executer(self, ctx: Contexte, objectif: str) -> Resultat:
        gestion = ctx.services.get("taches")
        if gestion is None:
            return Resultat.echec("Les tâches de fond ne sont pas disponibles.")
        t = gestion.lancer(objectif)
        return Resultat(True, f"Tâche n° {t.id} lancée en arrière-plan ; Mathieu sera notifié à la fin.")


class EtatTaches(Outil):
    nom = "etat_taches"
    description = "Liste les tâches de fond et leur état."

    async def executer(self, ctx: Contexte) -> Resultat:
        gestion = ctx.services.get("taches")
        taches = gestion.liste() if gestion else []
        if not taches:
            return Resultat(True, "Aucune tâche de fond.")
        return Resultat(True, "\n".join(f"n° {t['id']} ({t['etat']}) : {t['objectif']} — {t['resultat']}"
                                        for t in taches), donnees=taches)


class JournalActions(Outil):
    nom = "journal_actions"
    description = "Consulte le journal des dernières actions exécutées par Jarvis (quoi, quand, à la suite de quelle demande)."
    parametres = {"type": "object", "properties": {"nombre": {"type": "integer", "description": "Combien (10 par défaut)."}}}

    async def executer(self, ctx: Contexte, nombre: int = 10) -> Resultat:
        orchestrateur = ctx.services.get("orchestrateur")
        lignes = orchestrateur.journal.dernieres(min(nombre, 50)) if orchestrateur else []
        if not lignes:
            return Resultat(True, "Le journal est vide.")
        texte = "\n".join(f"{l['horodatage']} — {l['outil']} ({l['decision']}, {'ok' if l['ok'] else 'échec'}) "
                          f"suite à « {l['demande'][:80]} »" for l in lignes)
        return Resultat(True, texte, donnees=lignes)


class Heure(Outil):
    nom = "date_et_heure"
    description = "Donne la date et l'heure exactes."

    async def executer(self, ctx: Contexte) -> Resultat:
        m = datetime.now()
        return Resultat(True, f"Il est {m.hour} h {m.minute:02d}, nous sommes le {JOURS[m.weekday()]} {m.day} "
                              f"{MOIS[m.month - 1]}.", donnees={"iso": m.isoformat(timespec="minutes")})


OUTILS = [LancerTacheDeFond, EtatTaches, JournalActions, Heure]


class ReglerProactivite(Outil):
    nom = "regler_proactivite"
    description = ("Règle à quel point Jarvis prend des initiatives : silencieux (jamais de suggestion), discret "
                   "(2 par jour), actif (5 par jour, et propose les habitudes acceptées à l'heure habituelle).")
    parametres = {"type": "object", "properties": {"niveau": {"type": "string", "enum": ["silencieux", "discret", "actif"]}},
                  "required": ["niveau"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"passer la proactivité en mode {args.get('niveau')}"

    async def executer(self, ctx: Contexte, niveau: str) -> Resultat:
        application = ctx.services.get("application")
        initiative = getattr(application, "initiative", None)
        if initiative is None:
            return Resultat.echec("Module d'initiative indisponible.")
        initiative.regler_niveau(niveau)
        return Resultat(True, f"Proactivité : {niveau}.", donnees={"niveau": niveau})


OUTILS.append(ReglerProactivite)
