"""Point d'entrée : `python -m jarvis [commande]`.

Commandes :
  (aucune) / demarrer   lance Jarvis (voix, interface, icône, raccourcis)
  installer             télécharge les modèles et outils de la configuration
  diagnostic            mesures du lot J0 (voir A_VALIDER.md)
  banc                  banc de performance et batterie de commandes (PERF, NF-02)
  appairer              affiche un code d'appairage pour un téléphone ou le Mac
  appareils             liste / révoque les appareils appairés
  secrets               gère le coffre (mail, Discord, Spotify, Home Assistant…)
  sauvegarde            sauvegarde chiffrée maintenant ; --cle affiche la clé de secours
  outils                liste les outils et leur niveau de permission
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from logging.handlers import RotatingFileHandler


def configurer_journaux(verbeux: bool = False) -> None:
    from jarvis import chemins

    dossier = chemins.dossier_donnees() / "journaux"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = RotatingFileHandler(dossier / "jarvis.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    logging.basicConfig(level=logging.DEBUG if verbeux else logging.INFO, handlers=[fichier, console],
                        format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    for bruyant in ("httpx", "uvicorn.access", "comtypes", "PIL"):
        logging.getLogger(bruyant).setLevel(logging.WARNING)


def cmd_demarrer(args) -> int:
    from jarvis import config
    from jarvis.application import Jarvis

    config.creer_si_absent()
    jarvis = Jarvis(avec_voix=not args.sans_voix, avec_modeles=not args.sans_modeles)

    async def principal():
        if not args.sans_bureau:
            from jarvis.bureau import Bureau, ouvrir_fenetre

            Bureau(jarvis, asyncio.get_running_loop()).demarrer()
            if args.fenetre:
                ouvrir_fenetre(jarvis)
        print(f"Jarvis démarre. Interface : http://127.0.0.1:{jarvis.config.serveur.port}/#jeton={jarvis.appareils.jeton_local}")
        try:
            await jarvis.executer()
        except asyncio.CancelledError:
            pass
        finally:
            await jarvis.arreter()

    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_installer(args) -> int:
    from jarvis import config, modeles

    config.creer_si_absent()
    c = config.charger()
    fichiers = modeles.fichiers_necessaires(c)
    volume = sum(f.taille for f in fichiers if not modeles.chemin(f).exists())
    print(f"{len(fichiers)} fichiers, {volume / 1e9:.1f} Go à télécharger (github.com, huggingface.co ; vérifiés par SHA-256).")
    erreurs = modeles.installer(c, verifier=args.verifier)
    for e in erreurs:
        print("ERREUR", e)
    print("Installation terminée." if not erreurs else "Installation incomplète.")
    return 1 if erreurs else 0


def cmd_appairer(args) -> int:
    import httpx

    from jarvis import config

    c = config.charger()
    jeton = input("Jeton local affiché au démarrage de Jarvis (#jeton=…) : ").strip()
    r = httpx.post(f"http://127.0.0.1:{c.serveur.port}/api/appareils/code", headers={"Authorization": f"Bearer {jeton}"})
    r.raise_for_status()
    print(f"Code d'appairage : {r.json()['code']} (5 minutes). À saisir dans l'interface de l'appareil.")
    return 0


def cmd_appareils(args) -> int:
    from jarvis.serveur.appareils import Appareils

    a = Appareils()
    if args.revoquer:
        print("Révoqué." if a.revoquer(args.revoquer) else "Appareil inconnu.")
    for ap in a.lister():
        print(f"{ap['id']}  {ap['nom']}  ({ap['type']}, appairé le {ap['appaire']})")
    return 0


SECRETS_CONNUS = {
    "imap_mot_de_passe": "mot de passe d'application de la boîte mail (IMAP/SMTP)",
    "caldav_mot_de_passe": "mot de passe de l'agenda CalDAV",
    "discord_jeton_bot": "jeton du bot Discord de Mathieu",
    "home_assistant_jeton": "jeton longue durée Home Assistant",
    "postgame_jeton": "jeton de l'API locale Postgame (si elle en demande un)",
}


def cmd_secrets(args) -> int:
    from jarvis.securite.secrets import Coffre

    coffre = Coffre()
    if args.action == "lister":
        for nom in coffre.noms():
            print(nom)
        print("\nSecrets attendus par les intégrations :")
        for nom, aide in SECRETS_CONNUS.items():
            print(f"  {nom:24} {aide}")
    elif args.action == "definir":
        valeur = getpass.getpass(f"Valeur de {args.nom} (non affichée) : ")
        coffre.ecrire(args.nom, valeur)
        print("Enregistré, chiffré par DPAPI.")
    elif args.action == "supprimer":
        coffre.supprimer(args.nom)
        print("Supprimé.")
    return 0


def cmd_sauvegarde(args) -> int:
    from pathlib import Path

    from jarvis import config
    from jarvis.memoire import sauvegarde
    from jarvis.securite.secrets import Coffre

    coffre = Coffre()
    if args.cle:
        import base64

        print("Clé de secours (à noter hors du PC, elle seule permet de restaurer après une panne) :")
        print(base64.urlsafe_b64encode(sauvegarde.cle(coffre)).decode())
        return 0
    if args.restaurer:
        import base64

        cle = base64.urlsafe_b64decode(getpass.getpass("Clé de secours : ").strip())
        noms = sauvegarde.restaurer(Path(args.restaurer), cle, Path(args.vers or "restauration"))
        print("Restauré :", ", ".join(noms))
        return 0
    destination = config.charger().memoire.dossier_sauvegarde
    if not destination:
        print("Définir [memoire] dossier_sauvegarde dans jarvis.toml.")
        return 1
    print("Sauvegarde :", sauvegarde.sauvegarder(coffre, Path(destination)))
    return 0


def cmd_outils(args) -> int:
    from jarvis.outils.registre import Registre

    r = Registre().charger_tout()
    for nom, o in sorted(r.outils.items()):
        reseau = f" → {', '.join(o.hotes)}" if o.hotes else ""
        print(f"{o.niveau.nom_fr:12} {nom:36}{reseau}")
    for e in r.erreurs:
        print("ERREUR", e)
    print(f"\n{len(r.outils)} outils.")
    return 0


def cmd_diagnostic(args) -> int:
    from jarvis.diagnostic.__main__ import main as diagnostic

    return diagnostic(args.reste)


def cmd_enroler_voix(args) -> int:
    """Enregistre Mathieu (mot de réveil + phrases), calibre l'empreinte vocale (VOX-10, VOX-11)."""

    from jarvis import chemins
    from jarvis.diagnostic import audio
    from jarvis.diagnostic.micro import enregistrer
    from jarvis.securite.secrets import Coffre
    from jarvis.voix import locuteur
    from jarvis.voix.moteurs import Synthese

    dossier = chemins.dossier_donnees() / "voix_mathieu"
    (dossier / "reveil").mkdir(parents=True, exist_ok=True)
    (dossier / "ambiance").mkdir(parents=True, exist_ok=True)
    print("Enrôlement de ta voix : tout reste sur ce PC. Parle à ta distance habituelle du micro.")
    for i in range(args.nombre):
        input(f"  {i + 1}/{args.nombre} — Entrée, puis dis « Jarvis » (varie le ton : normal, appel, question…) ")
        audio.ecrire_wav(dossier / "reveil" / f"jarvis_{i:02d}.wav", enregistrer(2.0), 16000)
    phrases = ["Jarvis, quelle heure est-il ?", "Mets un peu de musique s'il te plaît.", "Oui, vas-y, envoie-le.",
               "Non, annule.", "Rappelle-moi demain matin d'appeler le garage.", "Qu'est-ce que tu sais sur moi ?"]
    sons = []
    for phrase in phrases:
        input(f"  Entrée, puis lis : « {phrase} » ")
        son = enregistrer(4.0)
        sons.append(son)
        audio.ecrire_wav(dossier / f"phrase_{len(sons)}.wav", son, 16000)
    if args.ambiance:
        input(f"  Lance une partie (ou ton ambiance habituelle), puis Entrée : {args.ambiance} s d'enregistrement ")
        audio.ecrire_wav(dossier / "ambiance" / "ambiance.wav", enregistrer(float(args.ambiance)), 16000)
    print("Calibrage de l'empreinte vocale…")
    ex = locuteur.Extracteur()
    siennes = [ex.empreinte(s) for s in sons]
    autres = []
    synth = Synthese("piper-siwis", prechauffer=False)
    for phrase in phrases:
        son, taux = synth.synthetiser(phrase)
        autres.append(ex.empreinte(audio.reechantillonner(son, taux)))
    calibration = locuteur.calibrer(siennes, autres)
    locuteur.VerificateurLocuteur(Coffre()).enregistrer(calibration)
    print(f"Empreinte enregistrée (chiffrée). Seuil {calibration['seuil']}, similarité minimale de ta voix "
          f"{calibration['min_mathieu']}. Lance maintenant : python -m jarvis entrainer-reveil")
    return 0


def cmd_entrainer_reveil(args) -> int:
    from pathlib import Path

    from jarvis import chemins
    from jarvis.voix import entrainement_reveil as er

    dossier = chemins.dossier_donnees() / "voix_mathieu"
    enregistrements = Path(args.enregistrements) if args.enregistrements else dossier / "reveil"
    ambiance = Path(args.ambiance) if args.ambiance else dossier / "ambiance"
    print("Fabrication du corpus (voix de synthèse + tes enregistrements), quelques minutes…")
    corpus = er.construire_corpus(enregistrements, ambiance, repetitions=args.repetitions)
    print(f"  {len(corpus.positifs)} exemples positifs, {len(corpus.negatifs)} négatifs. Entraînement…")
    m = er.entrainer(corpus)
    print(f"Modèle : {m['fichier']}")
    print(f"  détection {m['detection']:.0%} (exemples de test), seuil {m['seuil']}, "
          f"faux par fenêtre {m['faux_par_fenetre']:.2%}")
    print("Chaque détection est confirmée par la transcription : un faux déclenchement ne réveille pas Jarvis.")
    print("Redémarre Jarvis pour l'utiliser (le téléphone le récupère aussi au prochain démarrage du réveil).")
    return 0


def cmd_banc(args) -> int:
    from jarvis.banc import main as banc

    return banc(args.reste)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    brut = list(sys.argv[1:] if argv is None else argv)
    if brut and brut[0] in ("diagnostic", "banc"):  # options transmises telles quelles au sous-programme
        if brut[0] == "diagnostic":
            from jarvis.diagnostic.__main__ import main as diagnostic

            return diagnostic(brut[1:])
        from jarvis.banc import main as banc

        return banc(brut[1:])
    p = argparse.ArgumentParser(prog="jarvis", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbeux", action="store_true")
    sous = p.add_subparsers(dest="commande")
    d = sous.add_parser("demarrer")
    d.add_argument("--sans-voix", action="store_true")
    d.add_argument("--sans-modeles", action="store_true", help="n'lance pas llama-server (url_externe ou tests)")
    d.add_argument("--sans-bureau", action="store_true")
    d.add_argument("--fenetre", action="store_true", help="ouvre la fenêtre au démarrage")
    i = sous.add_parser("installer")
    i.add_argument("--verifier", action="store_true", help="revérifie l'empreinte des fichiers présents")
    sous.add_parser("appairer")
    a = sous.add_parser("appareils")
    a.add_argument("--revoquer")
    s = sous.add_parser("secrets")
    s.add_argument("action", choices=["lister", "definir", "supprimer"])
    s.add_argument("nom", nargs="?")
    sv = sous.add_parser("sauvegarde")
    sv.add_argument("--cle", action="store_true")
    sv.add_argument("--restaurer")
    sv.add_argument("--vers")
    sous.add_parser("outils")
    ev = sous.add_parser("enroler-voix")
    ev.add_argument("--nombre", type=int, default=15, help="nombre de « Jarvis » à enregistrer")
    ev.add_argument("--ambiance", type=int, default=0, help="secondes d'ambiance de jeu à enregistrer (ex. 120)")
    er_ = sous.add_parser("entrainer-reveil")
    er_.add_argument("--enregistrements")
    er_.add_argument("--ambiance")
    er_.add_argument("--repetitions", type=int, default=4)
    for nom in ("diagnostic", "banc"):
        x = sous.add_parser(nom, add_help=False)
        x.add_argument("reste", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    commande = args.commande or "demarrer"
    if commande == "demarrer" and not hasattr(args, "sans_voix"):
        args = p.parse_args(["demarrer", *(argv or sys.argv[1:])])
    if commande not in ("diagnostic", "banc"):
        configurer_journaux(args.verbeux)
    return {"demarrer": cmd_demarrer, "installer": cmd_installer, "appairer": cmd_appairer,
            "appareils": cmd_appareils, "secrets": cmd_secrets, "sauvegarde": cmd_sauvegarde, "outils": cmd_outils,
            "diagnostic": cmd_diagnostic, "banc": cmd_banc, "enroler-voix": cmd_enroler_voix,
            "entrainer-reveil": cmd_entrainer_reveil}[commande](args)


if __name__ == "__main__":
    sys.exit(main())
