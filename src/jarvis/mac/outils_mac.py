"""Outils du Mac (MAC-03, MAC-05) : déclarés au cerveau du PC, exécutés localement sur le Mac.

Chaque outil a le même niveau de permission que son équivalent Windows (SEC-01). Le pilotage
passe par AppleScript (`osascript`), `open`, Spotlight (`mdfind`) et `screencapture`.
"""

from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


def echapper(texte: str) -> str:
    """Chaîne AppleScript sûre (pas d'injection de code par des guillemets)."""
    return '"' + str(texte).replace("\\", "\\\\").replace('"', '\\"') + '"'


def osascript(script: str, delai: float = 20) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=delai)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "AppleScript a échoué")
    return r.stdout.strip()


def _obj(proprietes: dict, requis: list[str] | None = None) -> dict:
    return {"type": "object", "properties": proprietes, "required": requis or []}


DEFINITIONS = [
    {"nom": "lancer_application", "description": "Ouvre une application du Mac.", "niveau": "reversible",
     "parametres": _obj({"nom": {"type": "string"}}, ["nom"])},
    {"nom": "fermer_application", "description": "Quitte proprement une application du Mac.", "niveau": "reversible",
     "parametres": _obj({"nom": {"type": "string"}}, ["nom"])},
    {"nom": "regler_volume", "description": "Règle le volume du Mac (0 à 100) ou le coupe.", "niveau": "reversible",
     "parametres": _obj({"niveau": {"type": "integer"}, "muet": {"type": "boolean"}})},
    {"nom": "chercher_fichiers", "description": "Cherche des fichiers sur le Mac (Spotlight, nom et contenu).",
     "niveau": "lecture", "parametres": _obj({"requete": {"type": "string"}}, ["requete"])},
    {"nom": "ouvrir_fichier", "description": "Ouvre un fichier ou une adresse sur le Mac.", "niveau": "reversible",
     "parametres": _obj({"chemin": {"type": "string"}}, ["chemin"])},
    {"nom": "creer_rappel", "description": "Crée un rappel dans l'app Rappels du Mac (synchronisée iCloud).",
     "niveau": "reversible", "parametres": _obj({"texte": {"type": "string"},
                                                 "quand": {"type": "string", "description": "ISO 8601"}}, ["texte"])},
    {"nom": "agenda_du_jour", "description": "Liste les évènements du jour dans Calendrier du Mac.", "niveau": "lecture",
     "lit_contenu_externe": True, "parametres": _obj({})},
    {"nom": "creer_note", "description": "Crée une note dans Notes du Mac.", "niveau": "reversible",
     "parametres": _obj({"titre": {"type": "string"}, "texte": {"type": "string"}}, ["texte"])},
    {"nom": "mails_non_lus", "description": "Liste les mails non lus de Mail sur le Mac.", "niveau": "lecture",
     "lit_contenu_externe": True, "parametres": _obj({"nombre": {"type": "integer"}})},
    {"nom": "envoyer_mail", "description": "Envoie un mail depuis Mail du Mac. Toujours confirmé.", "niveau": "irreversible",
     "parametres": _obj({"destinataire": {"type": "string"}, "sujet": {"type": "string"}, "corps": {"type": "string"}},
                        ["destinataire", "sujet", "corps"])},
    {"nom": "analyser_ecran", "description": "Capture l'écran du Mac et l'analyse avec le modèle de vision du PC.",
     "niveau": "lecture", "lit_contenu_externe": True, "parametres": _obj({"question": {"type": "string"}}, ["question"])},
    {"nom": "sonner", "description": "Fait sonner le Mac pour le retrouver.", "niveau": "lecture", "parametres": _obj({})},
]


def executer(outil: str, args: dict, vision=None) -> tuple[bool, str]:
    """Exécute un outil ; `vision(png, question) -> str` délègue l'analyse d'image au PC."""
    try:
        if outil == "lancer_application":
            r = subprocess.run(["open", "-a", args["nom"]], capture_output=True, text=True, timeout=20)
            return (r.returncode == 0, f"{args['nom']} ouvert." if r.returncode == 0 else r.stderr.strip())
        if outil == "fermer_application":
            osascript(f"tell application {echapper(args['nom'])} to quit")
            return True, f"{args['nom']} fermé."
        if outil == "regler_volume":
            if args.get("muet") is not None:
                osascript(f"set volume output muted {'true' if args['muet'] else 'false'}")
            if args.get("niveau") is not None:
                niveau = max(0, min(100, int(args["niveau"])))
                osascript(f"set volume output volume {niveau}")
            return True, f"Volume du Mac : {osascript('output volume of (get volume settings)')} %."
        if outil == "chercher_fichiers":
            r = subprocess.run(["mdfind", "-onlyin", str(Path.home()), args["requete"]], capture_output=True, text=True,
                               timeout=20)
            lignes = [ligne for ligne in r.stdout.splitlines() if ligne][:15]
            return True, ("; ".join(lignes) if lignes else "Aucun fichier trouvé.")
        if outil == "ouvrir_fichier":
            r = subprocess.run(["open", args["chemin"]], capture_output=True, text=True, timeout=20)
            return (r.returncode == 0, "Ouvert." if r.returncode == 0 else r.stderr.strip())
        if outil == "creer_rappel":
            proprietes = f"name:{echapper(args['texte'])}"
            if args.get("quand"):
                secondes = int((datetime.fromisoformat(args["quand"]) - datetime.now()).total_seconds())
                proprietes += f", remind me date:((current date) + {max(secondes, 0)})"
            osascript(f'tell application "Reminders" to make new reminder with properties {{{proprietes}}}')
            return True, f"Rappel créé : {args['texte']}."
        if outil == "agenda_du_jour":
            script = '''set debut to current date
set hours of debut to 0
set minutes of debut to 0
set seconds of debut to 0
set fin to debut + 86400
set sortie to ""
tell application "Calendar"
  repeat with c in calendars
    repeat with e in (every event of c whose start date ≥ debut and start date < fin)
      set sortie to sortie & (time string of (start date of e)) & " " & (summary of e) & linefeed
    end repeat
  end repeat
end tell
return sortie'''
            texte = osascript(script, delai=60)
            return True, texte or "Rien dans le Calendrier aujourd'hui."
        if outil == "creer_note":
            corps = f"<h1>{args.get('titre', '')}</h1>{args['texte']}" if args.get("titre") else args["texte"]
            osascript(f'tell application "Notes" to make new note with properties {{body:{echapper(corps)}}}')
            return True, "Note créée."
        if outil == "mails_non_lus":
            n = max(1, min(int(args.get("nombre", 10)), 30))
            script = f'''set sortie to ""
tell application "Mail"
  set liste to (messages of inbox whose read status is false)
  repeat with i from 1 to (count of liste)
    if i > {n} then exit repeat
    set m to item i of liste
    set sortie to sortie & (sender of m) & " — " & (subject of m) & linefeed
  end repeat
end tell
return sortie'''
            return True, osascript(script, delai=60) or "Aucun mail non lu."
        if outil == "envoyer_mail":
            script = f'''tell application "Mail"
  set m to make new outgoing message with properties {{subject:{echapper(args["sujet"])}, content:{echapper(args["corps"])}, visible:false}}
  tell m to make new to recipient with properties {{address:{echapper(args["destinataire"])}}}
  send m
end tell'''
            osascript(script)
            return True, f"Mail envoyé à {args['destinataire']}."
        if outil == "analyser_ecran":
            if vision is None:
                return False, "Vision indisponible (PC injoignable)."
            with tempfile.TemporaryDirectory() as d:
                chemin = Path(d) / "ecran.png"
                subprocess.run(["screencapture", "-x", "-t", "png", str(chemin)], check=True, timeout=20)
                return True, vision(chemin.read_bytes(), args["question"])
        if outil == "sonner":
            for _ in range(3):
                subprocess.run(["afplay", "/System/Library/Sounds/Sosumi.aiff"], timeout=10)
            return True, "Le Mac a sonné."
    except Exception as e:  # noqa: BLE001 — l'erreur est rendue au cerveau, qui la dit honnêtement
        return False, f"Erreur sur le Mac : {e}"
    return False, f"Outil inconnu sur le Mac : {outil}"
