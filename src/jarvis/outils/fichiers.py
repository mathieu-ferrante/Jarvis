"""OUT-FIC : chercher (nom et contenu), ouvrir, lire / résumer, ranger, renommer, convertir, supprimer.

Les déplacements sont journalisés pour pouvoir être annulés (« annule le dernier rangement »).
La suppression passe par la corbeille (récupérable) mais reste confirmée (SEC-01).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from jarvis import chemins
from jarvis.outils import windows as win
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

EXTENSIONS_TEXTE = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".xml", ".log", ".ini", ".toml",
                    ".yaml", ".yml", ".kt", ".java", ".c", ".cpp", ".h", ".rs", ".go", ".ps1", ".bat", ".gd", ".sql"}
CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg"},
    "Vidéos": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "Musique": {".mp3", ".flac", ".wav", ".ogg", ".m4a"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".xlsx", ".xls", ".ods", ".pptx", ".csv"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installateurs": {".exe", ".msi"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".kt", ".gd", ".ps1"},
}
DUREE_MAX_PARCOURS_S = 8


def dossiers_utilisateur() -> list[Path]:
    accueil = Path.home()
    noms = ["Desktop", "Bureau", "Documents", "Downloads", "Téléchargements", "Pictures", "Images", "Videos",
            "Vidéos", "Music", "Musique", "OneDrive"]
    return [accueil / n for n in noms if (accueil / n).exists()]


def resoudre(chemin: str) -> Path:
    """Accepte « Téléchargements/x.pdf », « ~/Bureau », un chemin absolu…"""
    chemin = os.path.expandvars(os.path.expanduser(chemin.strip().strip('"')))
    p = Path(chemin)
    if p.is_absolute():
        return p
    alias = {"bureau": "Desktop", "téléchargements": "Downloads", "telechargements": "Downloads",
             "images": "Pictures", "vidéos": "Videos", "musique": "Music", "documents": "Documents"}
    premier, *reste = p.parts or ("",)
    if premier.lower() in alias:
        return Path.home() / alias[premier.lower()] / Path(*reste) if reste else Path.home() / alias[premier.lower()]
    return Path.home() / p


def recherche_windows(requete: str, contenu: bool, n: int = 20) -> list[str] | None:
    """Index de Windows Search (rapide, nom et contenu). None si indisponible."""
    if not win.WINDOWS:
        return None
    echappe = requete.replace("'", "''").replace('"', "")
    condition = (f"CONTAINS(*, '\"{echappe}*\"')" if contenu
                 else f"System.FileName LIKE '%{echappe}%'")
    script = (
        "$c = New-Object -ComObject ADODB.Connection; $r = New-Object -ComObject ADODB.Recordset;"
        "$c.Open(\"Provider=Search.CollatorDSO;Extended Properties='Application=Windows';\");"
        f"$r.Open(\"SELECT TOP {n} System.ItemPathDisplay FROM SYSTEMINDEX WHERE SCOPE='file:{Path.home().as_posix()}' "
        f"AND {condition} ORDER BY System.DateModified DESC\", $c);"
        "while(-not $r.EOF){ $r.Fields.Item('System.ItemPathDisplay').Value; $r.MoveNext() }"
    )
    try:
        sortie = win.powershell(script, delai=15)
    except Exception:  # noqa: BLE001
        return None
    if sortie.returncode != 0:
        return None
    return [ligne.strip() for ligne in sortie.stdout.splitlines() if ligne.strip()]


def parcourir(requete: str, racines: list[Path], type_fichier: str = "", n: int = 20) -> list[str]:
    """Repli : parcours des dossiers, correspondance approchée sur le nom."""
    mots = [m for m in re.findall(r"\w+", requete.lower()) if len(m) > 1]
    trouves: list[tuple[float, str]] = []
    debut = time.monotonic()
    for racine in racines:
        for dossier, sous, fichiers in os.walk(racine):
            sous[:] = [s for s in sous if not s.startswith((".", "node_modules", "__pycache__", "AppData"))]
            if time.monotonic() - debut > DUREE_MAX_PARCOURS_S:
                break
            for f in fichiers:
                if type_fichier and not f.lower().endswith("." + type_fichier.lower().lstrip(".")):
                    continue
                nom = f.lower()
                score = sum(m in nom for m in mots) / max(len(mots), 1)
                if score == 0:
                    score = difflib.SequenceMatcher(None, requete.lower(), Path(nom).stem).ratio() - 0.5
                if score > 0:
                    trouves.append((score, str(Path(dossier) / f)))
    trouves.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, c in trouves[:n]]


def extraire_texte(chemin: Path, limite: int = 12000) -> str:
    ext = chemin.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        lecteur = PdfReader(str(chemin))
        texte = ""
        for page in lecteur.pages:
            texte += (page.extract_text() or "") + "\n"
            if len(texte) > limite:
                break
        return texte[:limite]
    if ext in (".docx", ".odt", ".pptx"):
        with zipfile.ZipFile(chemin) as z:
            noms = [n for n in z.namelist() if n in ("word/document.xml", "content.xml") or n.startswith("ppt/slides/slide")]
            xml = " ".join(z.read(n).decode("utf-8", "replace") for n in noms)
        xml = re.sub(r"</w:p>|</text:p>|</a:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)[:limite]
    if ext in EXTENSIONS_TEXTE or chemin.stat().st_size < 200_000:
        return chemin.read_text("utf-8", errors="replace")[:limite]
    raise ValueError(f"Format non lisible : {ext}")


# --- Annulation des déplacements ------------------------------------------------------------


def _journal_operations() -> Path:
    return chemins.dossier_donnees() / "operations_fichiers.jsonl"


def consigner_operation(deplacements: list[tuple[str, str]], libelle: str) -> None:
    fichier = _journal_operations()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    with open(fichier, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": datetime.now().isoformat(timespec="seconds"), "libelle": libelle,
                            "deplacements": deplacements}, ensure_ascii=False) + "\n")


def derniere_operation() -> dict | None:
    fichier = _journal_operations()
    if not fichier.exists():
        return None
    lignes = [ligne for ligne in fichier.read_text("utf-8").splitlines() if ligne.strip()]
    return json.loads(lignes[-1]) if lignes else None


def retirer_derniere_operation() -> None:
    fichier = _journal_operations()
    lignes = [ligne for ligne in fichier.read_text("utf-8").splitlines() if ligne.strip()]
    fichier.write_text("\n".join(lignes[:-1]) + ("\n" if lignes[:-1] else ""), "utf-8")


def deplacer_sans_ecraser(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    cible = destination
    i = 2
    while cible.exists():
        cible = destination.with_name(f"{destination.stem} ({i}){destination.suffix}")
        i += 1
    shutil.move(str(source), str(cible))
    return cible


# --- Outils ---------------------------------------------------------------------------------


class ChercherFichiers(Outil):
    nom = "chercher_fichiers"
    description = "Cherche des fichiers sur le PC par nom ou par contenu (index Windows, sinon parcours des dossiers)."
    parametres = {"type": "object", "properties": {
        "requete": {"type": "string", "description": "Mots-clés."},
        "dans_le_contenu": {"type": "boolean", "description": "Chercher aussi dans le texte des fichiers."},
        "type_fichier": {"type": "string", "description": "Extension facultative, ex. pdf."},
        "dossier": {"type": "string", "description": "Dossier où chercher (facultatif)."}},
        "required": ["requete"]}

    async def executer(self, ctx: Contexte, requete: str, dans_le_contenu: bool = False, type_fichier: str = "",
                       dossier: str = "") -> Resultat:
        resultats = None
        if not dossier:
            resultats = await asyncio.to_thread(recherche_windows, requete, dans_le_contenu)
            if resultats is not None and type_fichier:
                resultats = [r for r in resultats if r.lower().endswith("." + type_fichier.lower().lstrip("."))]
        if not resultats:
            racines = [resoudre(dossier)] if dossier else dossiers_utilisateur()
            resultats = await asyncio.to_thread(parcourir, requete, racines, type_fichier)
        if not resultats:
            return Resultat(True, f"Aucun fichier trouvé pour « {requete} ».", donnees=[])
        return Resultat(True, f"{len(resultats)} fichier(s) : " + " ; ".join(resultats[:10]), donnees=resultats)


class OuvrirFichier(Outil):
    nom = "ouvrir_fichier"
    description = "Ouvre un fichier ou un dossier avec l'application par défaut."
    parametres = {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    def decrire(self, args):
        return f"ouvrir {args.get('chemin')}"

    async def executer(self, ctx: Contexte, chemin: str) -> Resultat:
        p = resoudre(chemin)
        if not p.exists():
            return Resultat.echec(f"{p} n'existe pas.")
        os.startfile(str(p))  # noqa: S606
        return Resultat(True, f"{p.name} ouvert.")


class LireFichier(Outil):
    nom = "lire_fichier"
    description = ("Lit le texte d'un document (txt, md, pdf, docx, code…) pour le résumer, répondre à une question "
                   "dessus ou le traduire.")
    parametres = {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, chemin: str) -> Resultat:
        p = resoudre(chemin)
        if not p.is_file():
            return Resultat.echec(f"{p} n'est pas un fichier.")
        try:
            texte = await asyncio.to_thread(extraire_texte, p)
        except Exception as e:  # noqa: BLE001
            return Resultat.echec(f"Lecture impossible : {e}")
        return Resultat(True, f"Contenu de {p.name} :\n{texte}", contenu_externe=True)


class DeplacerFichier(Outil):
    nom = "deplacer_ou_renommer"
    description = "Déplace ou renomme un fichier ou un dossier (sans jamais écraser un fichier existant)."
    parametres = {"type": "object", "properties": {
        "source": {"type": "string"}, "destination": {"type": "string", "description": "Nouveau chemin ou nouveau nom."}},
        "required": ["source", "destination"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"déplacer {args.get('source')} vers {args.get('destination')}"

    async def executer(self, ctx: Contexte, source: str, destination: str) -> Resultat:
        src = resoudre(source)
        if not src.exists():
            return Resultat.echec(f"{src} n'existe pas.")
        dest = Path(destination)
        dest = src.with_name(destination) if len(dest.parts) == 1 else resoudre(destination)
        if dest.is_dir():
            dest = dest / src.name
        final = deplacer_sans_ecraser(src, dest)
        consigner_operation([(str(src), str(final))], f"déplacement de {src.name}")
        return Resultat(True, f"{src.name} → {final}", donnees={"final": str(final), "source": str(src)})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return Path(resultat.donnees["final"]).exists() and not Path(resultat.donnees["source"]).exists()


class RangerDossier(Outil):
    nom = "ranger_dossier"
    description = ("Range les fichiers d'un dossier (ex. Téléchargements) dans des sous-dossiers par type "
                   "(Images, Documents, Vidéos…). Annulable.")
    parametres = {"type": "object", "properties": {"dossier": {"type": "string"},
                                                   "simulation": {"type": "boolean", "description": "Seulement décrire."}},
                  "required": ["dossier"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"ranger le dossier {args.get('dossier')} par type de fichier"

    async def executer(self, ctx: Contexte, dossier: str, simulation: bool = False) -> Resultat:
        racine = resoudre(dossier)
        if not racine.is_dir():
            return Resultat.echec(f"{racine} n'est pas un dossier.")
        plan: list[tuple[Path, Path]] = []
        for f in racine.iterdir():
            if not f.is_file():
                continue
            categorie = next((c for c, exts in CATEGORIES.items() if f.suffix.lower() in exts), None)
            if categorie:
                plan.append((f, racine / categorie / f.name))
        if not plan:
            return Resultat(True, "Rien à ranger.")
        resume: dict[str, int] = {}
        for _, d in plan:
            resume[d.parent.name] = resume.get(d.parent.name, 0) + 1
        texte = ", ".join(f"{n} vers {c}" for c, n in resume.items())
        if simulation:
            return Resultat(True, f"Je rangerais {len(plan)} fichiers : {texte}.")
        faits = [(str(s), str(deplacer_sans_ecraser(s, d))) for s, d in plan]
        consigner_operation(faits, f"rangement de {racine.name}")
        return Resultat(True, f"{len(faits)} fichiers rangés : {texte}. Annulable.", donnees={"faits": faits})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        if not resultat.donnees:
            return None
        return all(Path(d).exists() for _, d in resultat.donnees["faits"])


class AnnulerOperation(Outil):
    nom = "annuler_derniere_operation_fichiers"
    description = "Annule le dernier déplacement, renommage ou rangement de fichiers fait par Jarvis."
    niveau = Niveau.REVERSIBLE

    async def executer(self, ctx: Contexte) -> Resultat:
        op = derniere_operation()
        if not op:
            return Resultat.echec("Aucune opération à annuler.")
        remis = 0
        for source, final in reversed(op["deplacements"]):
            if Path(final).exists() and not Path(source).exists():
                Path(source).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(final, source)
                remis += 1
        retirer_derniere_operation()
        return Resultat(True, f"Annulé : {op['libelle']} ({remis} élément(s) remis en place).")


class CreerDossier(Outil):
    nom = "creer_dossier"
    description = "Crée un dossier."
    parametres = {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}
    niveau = Niveau.REVERSIBLE

    async def executer(self, ctx: Contexte, chemin: str) -> Resultat:
        p = resoudre(chemin)
        p.mkdir(parents=True, exist_ok=True)
        return Resultat(True, f"Dossier {p} prêt.", donnees={"p": str(p)})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return Path(resultat.donnees["p"]).is_dir()


class SupprimerFichier(Outil):
    nom = "supprimer_fichier"
    description = "Met un fichier ou un dossier à la corbeille."
    parametres = {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}
    niveau = Niveau.IRREVERSIBLE
    windows_seulement = True

    def decrire(self, args):
        return f"mettre à la corbeille {resoudre(args.get('chemin', ''))}"

    async def executer(self, ctx: Contexte, chemin: str) -> Resultat:
        p = resoudre(chemin)
        if not p.exists():
            return Resultat.echec(f"{p} n'existe pas.")
        if not await asyncio.to_thread(win.mettre_a_la_corbeille, p):
            return Resultat.echec("Windows a refusé la mise à la corbeille.")
        return Resultat(True, f"{p.name} est dans la corbeille.", donnees={"p": str(p)})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return not Path(resultat.donnees["p"]).exists()


class ConvertirFichier(Outil):
    nom = "convertir_fichier"
    description = "Convertit un fichier : image (png, jpg, webp, bmp), ou document (pdf, docx…) vers texte (txt)."
    parametres = {"type": "object", "properties": {
        "chemin": {"type": "string"}, "format": {"type": "string", "enum": ["png", "jpg", "webp", "bmp", "txt"]}},
        "required": ["chemin", "format"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"convertir {args.get('chemin')} en {args.get('format')}"

    async def executer(self, ctx: Contexte, chemin: str, format: str) -> Resultat:  # noqa: A002
        src = resoudre(chemin)
        if not src.is_file():
            return Resultat.echec(f"{src} introuvable.")
        dest = src.with_suffix("." + format)
        i = 2
        while dest.exists():
            dest = src.with_name(f"{src.stem} ({i}).{format}")
            i += 1
        if format == "txt":
            texte = await asyncio.to_thread(extraire_texte, src, 10_000_000)
            dest.write_text(texte, "utf-8")
        else:
            from PIL import Image

            def convertir():
                with Image.open(src) as image:
                    (image.convert("RGB") if format in ("jpg", "bmp") else image).save(
                        dest, "JPEG" if format == "jpg" else format.upper())

            await asyncio.to_thread(convertir)
        return Resultat(True, f"Converti : {dest}", donnees={"p": str(dest)})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return Path(resultat.donnees["p"]).stat().st_size > 0


OUTILS = [ChercherFichiers, OuvrirFichier, LireFichier, DeplacerFichier, RangerDossier, AnnulerOperation,
          CreerDossier, SupprimerFichier, ConvertirFichier]
