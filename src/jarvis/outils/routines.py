"""OUT-ROU : routines nommées (« mode jeu »). Chaque étape repasse par les permissions de l'orchestrateur.

Les routines viennent de `jarvis.toml` ([routines.<nom>]) et de `routines.json` (créées par la voix).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from jarvis import chemins
from jarvis.llm.client import AppelOutil
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat


def _cle(nom: str) -> str:
    nom = unicodedata.normalize("NFKD", nom.lower())
    nom = "".join(c for c in nom if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", nom).strip("_")


def _fichier() -> Path:
    return chemins.dossier_donnees() / "routines.json"


def toutes(ctx: Contexte) -> dict[str, dict]:
    routines = {_cle(k): v for k, v in (getattr(ctx.config, "routines", None) or {}).items()}
    if _fichier().exists():
        routines.update({_cle(k): v for k, v in json.loads(_fichier().read_text("utf-8")).items()})
    return routines


class LancerRoutine(Outil):
    nom = "lancer_routine"
    description = "Lance une routine nommée (enchaînement d'actions), par exemple « mode jeu »."
    parametres = {"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"lancer la routine {args.get('nom')}"

    async def executer(self, ctx: Contexte, nom: str) -> Resultat:
        routines = toutes(ctx)
        cle = _cle(nom)
        if cle not in routines:
            proches = [k for k in routines if cle in k or k in cle]
            if not proches:
                return Resultat.echec(f"Routine inconnue : {nom}. Routines : {', '.join(routines) or 'aucune'}.")
            cle = proches[0]
        orchestrateur = ctx.services.get("orchestrateur")
        if orchestrateur is None:
            return Resultat.echec("Orchestrateur indisponible.")
        from jarvis.agent.orchestrateur import Tour

        tour = Tour(f"routine {cle}", "texte", "routine", "routine")
        bilan = []
        for i, etape in enumerate(routines[cle].get("etapes", [])):
            r = await orchestrateur.executer_appel(AppelOutil(f"r{i}", etape["outil"], dict(etape.get("args", {}))), tour)
            bilan.append(f"{etape['outil']} : {'ok' if r.ok else 'échec (' + r.message[:80] + ')'}")
        reussies = sum("ok" in b for b in bilan)
        return Resultat(reussies == len(bilan), f"Routine {cle} : {reussies}/{len(bilan)} étapes réussies. "
                        + " ; ".join(bilan))


class ListerRoutines(Outil):
    nom = "lister_routines"
    description = "Liste les routines disponibles et leurs étapes."

    async def executer(self, ctx: Contexte) -> Resultat:
        routines = toutes(ctx)
        if not routines:
            return Resultat(True, "Aucune routine définie.")
        return Resultat(True, " ; ".join(
            f"{k} : " + ", ".join(e["outil"] for e in v.get("etapes", [])) for k, v in routines.items()))


class CreerRoutine(Outil):
    nom = "creer_routine"
    description = "Crée ou remplace une routine : liste d'étapes {outil, args} utilisant les outils existants."
    parametres = {"type": "object", "properties": {
        "nom": {"type": "string"}, "description": {"type": "string"},
        "etapes": {"type": "array", "items": {"type": "object", "properties": {
            "outil": {"type": "string"}, "args": {"type": "object"}}, "required": ["outil"]}}},
        "required": ["nom", "etapes"]}
    niveau = Niveau.REVERSIBLE

    async def executer(self, ctx: Contexte, nom: str, etapes: list, description: str = "") -> Resultat:
        orchestrateur = ctx.services.get("orchestrateur")
        inconnus = [e.get("outil") for e in etapes if orchestrateur and e.get("outil") not in orchestrateur.registre]
        if inconnus:
            return Resultat.echec(f"Outils inconnus dans la routine : {', '.join(map(str, inconnus))}.")
        fichier = _fichier()
        donnees = json.loads(fichier.read_text("utf-8")) if fichier.exists() else {}
        donnees[_cle(nom)] = {"description": description, "etapes": etapes}
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), "utf-8")
        return Resultat(True, f"Routine {_cle(nom)} enregistrée ({len(etapes)} étapes).")


OUTILS = [LancerRoutine, ListerRoutines, CreerRoutine]
