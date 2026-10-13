"""OUT-CODE : exécution de code pour calculer, transformer, automatiser.

Python tourne dans un bac à sable : processus séparé en mode isolé, crochet d'audit qui interdit
le réseau, les sous-processus, ctypes, le registre et toute écriture hors de son dossier de
travail ; temps et mémoire limités. Niveau « réversible ».

PowerShell ne peut pas être confiné de la même façon : il est « irréversible », donc toujours
confirmé avec le script complet sous les yeux de Mathieu.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

DELAI_S = 20
MEMOIRE_MAX = 1_000_000_000
SORTIE_MAX = 6000

AMORCE = r'''
import sys, os
_TRAVAIL = os.path.realpath(sys.argv[2])
_INTERDITS = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile",
              "ctypes.", "winreg.", "_winapi.", "msvcrt.", "os.kill", "signal.")

def _dans_travail(chemin):
    try:
        return os.path.realpath(os.fspath(chemin)).startswith(_TRAVAIL)
    except (TypeError, ValueError):
        return False

def _crochet(evenement, args):
    if evenement.startswith(_INTERDITS) and evenement != "socket.__new__x":
        raise PermissionError(f"Bac à sable : {evenement} interdit")
    if evenement == "open":
        chemin, mode = args[0], args[1] or "r"
        if isinstance(mode, str) and any(c in mode for c in "wax+") and not _dans_travail(chemin):
            raise PermissionError("Bac à sable : écriture hors du dossier de travail interdite")
    if evenement in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree", "shutil.move",
                     "os.chmod", "os.truncate", "os.link", "os.symlink"):
        if not all(_dans_travail(a) for a in args if isinstance(a, (str, bytes, os.PathLike))):
            raise PermissionError(f"Bac à sable : {evenement} hors du dossier de travail interdit")

code = open(sys.argv[1], encoding="utf-8").read()
os.chdir(_TRAVAIL)
sys.addaudithook(_crochet)
exec(compile(code, "<jarvis>", "exec"), {"__name__": "__main__"})
'''


def executer_python_isole(code: str, delai: float = DELAI_S) -> dict:
    with tempfile.TemporaryDirectory(prefix="jarvis-bac-") as dossier:
        travail = Path(dossier) / "travail"
        travail.mkdir()
        (Path(dossier) / "code.py").write_text(code, "utf-8")
        (Path(dossier) / "amorce.py").write_text(AMORCE, "utf-8")
        processus = subprocess.Popen(
            [sys.executable, "-I", "-X", "utf8", str(Path(dossier) / "amorce.py"), str(Path(dossier) / "code.py"),
             str(travail)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=dossier,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        debut = time.monotonic()
        motif = ""
        surveille = psutil.Process(processus.pid)
        while processus.poll() is None:
            if time.monotonic() - debut > delai:
                motif = f"temps limite de {delai:.0f} s dépassé"
            else:
                try:
                    if surveille.memory_info().rss > MEMOIRE_MAX:
                        motif = "mémoire limite (1 Go) dépassée"
                except psutil.Error:
                    pass
            if motif:
                processus.kill()
                break
            time.sleep(0.05)
        sortie, erreurs = processus.communicate()
        fichiers = sorted(p.name for p in travail.iterdir())
    return {"code_retour": processus.returncode, "sortie": sortie.decode("utf-8", "replace")[-SORTIE_MAX:],
            "erreurs": erreurs.decode("utf-8", "replace")[-SORTIE_MAX:], "motif": motif, "fichiers": fichiers}


class ExecuterPython(Outil):
    nom = "executer_python"
    description = ("Exécute du code Python dans un bac à sable (sans réseau, sans accès en écriture aux fichiers, "
                   "20 s max) pour calculer ou transformer des données. Utilise print() pour le résultat.")
    parametres = {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return "exécuter un calcul en Python dans le bac à sable"

    async def executer(self, ctx: Contexte, code: str) -> Resultat:
        r = await asyncio.to_thread(executer_python_isole, code)
        if r["motif"]:
            return Resultat.echec(f"Arrêté : {r['motif']}.")
        if r["code_retour"] != 0:
            return Resultat.echec(f"Erreur :\n{r['erreurs'][-1500:]}")
        return Resultat(True, f"Sortie :\n{r['sortie'] or '(rien affiché)'}", donnees=r)


class ExecuterPowershell(Outil):
    nom = "executer_powershell"
    description = ("Exécute un script PowerShell sur le PC (automatisation Windows). Toujours confirmé par Mathieu, "
                   "script complet affiché.")
    parametres = {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}
    niveau = Niveau.IRREVERSIBLE
    windows_seulement = True

    def decrire(self, args):
        return f"exécuter ce script PowerShell : {args.get('script', '')[:500]}"

    async def executer(self, ctx: Contexte, script: str) -> Resultat:
        def lancer():
            return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                  capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        try:
            r = await asyncio.to_thread(lancer)
        except subprocess.TimeoutExpired:
            return Resultat.echec("Le script a dépassé 60 s.")
        texte = (r.stdout or "")[-SORTIE_MAX:]
        if r.returncode != 0:
            return Resultat.echec(f"Code {r.returncode} : {(r.stderr or '')[-1500:]}")
        return Resultat(True, f"Sortie :\n{texte or '(rien)'}")


OUTILS = [ExecuterPython, ExecuterPowershell]
