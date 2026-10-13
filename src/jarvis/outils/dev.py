"""OUT-DEV : projets perso — état d'un dépôt git, derniers changements, lancement des tests."""

from __future__ import annotations

import asyncio
import difflib
import subprocess
from pathlib import Path

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

DOSSIER_PROJETS = Path.home() / "Documents" / "Projetperso"


def depots(ctx: Contexte) -> dict[str, Path]:
    """Dépôts configurés, sinon tous les dépôts git de Documents/Projetperso."""
    trouves: dict[str, Path] = {}
    for chemin in getattr(ctx.config.integrations, "depots", []) or []:
        p = Path(chemin).expanduser()
        if (p / ".git").exists():
            trouves[p.name.lower()] = p
    if not trouves and DOSSIER_PROJETS.exists():
        for p in DOSSIER_PROJETS.iterdir():
            if (p / ".git").exists():
                trouves[p.name.lower()] = p
    return trouves


def trouver(ctx: Contexte, nom: str) -> Path | None:
    liste = depots(ctx)
    cle = nom.lower().replace(" ", "-")
    if cle in liste:
        return liste[cle]
    proches = difflib.get_close_matches(cle, list(liste), n=1, cutoff=0.6) or [k for k in liste if cle in k]
    return liste[proches[0]] if proches else None


def git(depot: Path, *args: str, delai: float = 30) -> str:
    r = subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True, timeout=delai,
                       encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout or r.stderr).strip()


def commande_de_tests(depot: Path) -> list[str] | None:
    if (depot / "pyproject.toml").exists() or (depot / "tests").exists():
        python = depot / ".venv" / "Scripts" / "python.exe"
        return [str(python) if python.exists() else "python", "-m", "pytest", "-q", "--no-header"]
    if (depot / "package.json").exists():
        return ["npm.cmd", "test", "--silent"]
    if (depot / "gradlew.bat").exists():
        return [str(depot / "gradlew.bat"), "test", "--quiet"]
    if (depot / "project.godot").exists():
        return None
    return None


class EtatDepot(Outil):
    nom = "etat_depot"
    description = "Donne l'état d'un projet perso (dépôt git) : branche, fichiers modifiés, derniers commits. Sans nom : liste les projets."
    parametres = {"type": "object", "properties": {"projet": {"type": "string"}}}

    async def executer(self, ctx: Contexte, projet: str = "") -> Resultat:
        if not projet:
            return Resultat(True, "Projets : " + ", ".join(sorted(depots(ctx))) or "aucun dépôt trouvé.")
        depot = trouver(ctx, projet)
        if depot is None:
            return Resultat.echec(f"Projet inconnu : {projet}. Projets : {', '.join(sorted(depots(ctx)))}.")
        branche = await asyncio.to_thread(git, depot, "branch", "--show-current")
        statut = await asyncio.to_thread(git, depot, "status", "--short")
        commits = await asyncio.to_thread(git, depot, "log", "-5", "--pretty=format:%h %ad %s", "--date=short")
        modifies = len([ligne for ligne in statut.splitlines() if ligne.strip()])
        return Resultat(True, f"{depot.name} — branche {branche or '?'}, {modifies} fichier(s) modifié(s).\n"
                              f"Derniers commits :\n{commits}\n{('Modifications :' + chr(10) + statut[:1500]) if statut else ''}")


class ResumerChangements(Outil):
    nom = "resumer_changements"
    description = "Récupère les changements récents d'un projet (commits et fichiers touchés) pour les résumer."
    parametres = {"type": "object", "properties": {
        "projet": {"type": "string"}, "depuis": {"type": "string", "description": "ex. « 1 week ago », « 3 days ago »."}},
        "required": ["projet"]}

    async def executer(self, ctx: Contexte, projet: str, depuis: str = "1 week ago") -> Resultat:
        depot = trouver(ctx, projet)
        if depot is None:
            return Resultat.echec(f"Projet inconnu : {projet}.")
        journal = await asyncio.to_thread(git, depot, "log", f"--since={depuis}", "--stat", "--pretty=format:%n%h %ad %s",
                                          "--date=short")
        return Resultat(True, f"Changements de {depot.name} depuis {depuis} :\n{journal[:6000] or 'aucun commit.'}")


class LancerTests(Outil):
    nom = "lancer_tests"
    description = "Lance les tests d'un projet perso (pytest, npm test, gradle) et rapporte le résultat."
    parametres = {"type": "object", "properties": {"projet": {"type": "string"}}, "required": ["projet"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"lancer les tests du projet {args.get('projet')}"

    async def executer(self, ctx: Contexte, projet: str) -> Resultat:
        depot = trouver(ctx, projet)
        if depot is None:
            return Resultat.echec(f"Projet inconnu : {projet}.")
        commande = commande_de_tests(depot)
        if commande is None:
            return Resultat.echec(f"Je ne sais pas lancer les tests de {depot.name}.")

        def lancer():
            return subprocess.run(commande, cwd=depot, capture_output=True, text=True, timeout=600, encoding="utf-8",
                                  errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        try:
            r = await asyncio.to_thread(lancer)
        except subprocess.TimeoutExpired:
            return Resultat.echec("Les tests ont dépassé 10 minutes.")
        except FileNotFoundError as e:
            return Resultat.echec(f"Outil introuvable : {e}")
        sortie = (r.stdout + "\n" + r.stderr).strip()
        return Resultat(r.returncode == 0, f"{'Tests verts' if r.returncode == 0 else 'Tests en échec'} ({depot.name}) :\n"
                                           f"{sortie[-2500:]}")


OUTILS = [EtatDepot, ResumerChangements, LancerTests]
