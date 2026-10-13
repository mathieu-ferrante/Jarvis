"""OUT-SYS : applications et jeux, fenêtres, volume, sortie audio, luminosité, veille, état du PC."""

from __future__ import annotations

import asyncio
import ctypes
import difflib
import os
import re
import subprocess
from pathlib import Path

import psutil

from jarvis.outils import windows as win
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

# Raccourcis connus : jeux Steam et clients courants (URI plus fiables qu'un raccourci).
ALIAS = {
    "counter-strike 2": "steam://rungameid/730", "counter strike": "steam://rungameid/730",
    "cs2": "steam://rungameid/730", "cs": "steam://rungameid/730",
    "geometry dash": "steam://rungameid/322170",
    "steam": "steam://open/main",
    "spotify": "spotify:",
    "discord": "discord://",
    "league of legends": r"C:\Riot Games\Riot Client\RiotClientServices.exe --launch-product=league_of_legends --launch-patchline=live",
    "lol": r"C:\Riot Games\Riot Client\RiotClientServices.exe --launch-product=league_of_legends --launch-patchline=live",
    "explorateur": "explorer.exe", "explorateur de fichiers": "explorer.exe",
    "bloc-notes": "notepad.exe", "bloc notes": "notepad.exe", "calculatrice": "calc.exe",
    "paramètres": "ms-settings:", "gestionnaire des tâches": "taskmgr.exe",
}
# Nom de processus attendu, pour vérifier le lancement / la fermeture (BRN-04)
PROCESSUS = {
    "spotify": ["spotify.exe"], "discord": ["discord.exe"], "steam": ["steam.exe", "steamwebhelper.exe"],
    "counter-strike 2": ["cs2.exe"], "cs2": ["cs2.exe"], "cs": ["cs2.exe"], "counter strike": ["cs2.exe"],
    "chrome": ["chrome.exe"], "firefox": ["firefox.exe"], "edge": ["msedge.exe"], "obs": ["obs64.exe"],
    "league of legends": ["leagueclient.exe", "riotclientservices.exe"], "lol": ["leagueclient.exe", "riotclientservices.exe"],
    "geometry dash": ["geometrydash.exe"], "bloc-notes": ["notepad.exe"], "bloc notes": ["notepad.exe"],
    "calculatrice": ["calculatorapp.exe", "calc.exe"], "vs code": ["code.exe"], "visual studio code": ["code.exe"],
}


def _normaliser(nom: str) -> str:
    return re.sub(r"\s+", " ", nom.lower().replace(".exe", "").replace("’", "'")).strip()


def raccourcis() -> dict[str, Path]:
    trouves: dict[str, Path] = {}
    for dossier in win.dossiers_menu_demarrer():
        for lnk in dossier.rglob("*.lnk"):
            nom = _normaliser(lnk.stem)
            if "désinstaller" in nom or "uninstall" in nom:
                continue
            trouves.setdefault(nom, lnk)
        for url in dossier.rglob("*.url"):  # raccourcis de jeux Steam
            trouves.setdefault(_normaliser(url.stem), url)
    return trouves


def trouver_application(nom: str) -> tuple[str, str] | None:
    """(cible à lancer, nom retenu) ou None."""
    n = _normaliser(nom)
    if n in ALIAS:
        return ALIAS[n], n
    liste = raccourcis()
    if n in liste:
        return str(liste[n]), n
    contient = [k for k in liste if n in k]
    if contient:
        k = min(contient, key=len)
        return str(liste[k]), k
    proches = difflib.get_close_matches(n, list(liste) + list(ALIAS), n=1, cutoff=0.75)
    if proches:
        k = proches[0]
        return (ALIAS[k] if k in ALIAS else str(liste[k])), k
    return None


def processus_correspondants(nom: str) -> list[psutil.Process]:
    n = _normaliser(nom)
    attendus = set(PROCESSUS.get(n, []))
    resultat = []
    for p in psutil.process_iter(["name"]):
        nom_p = (p.info["name"] or "").lower()
        if nom_p in attendus or (not attendus and n.replace(" ", "") in nom_p.replace(".exe", "").replace(" ", "")):
            resultat.append(p)
    return resultat


class LancerApplication(Outil):
    nom = "lancer_application"
    description = "Lance une application ou un jeu installé (Spotify, Discord, Steam, Counter-Strike 2, LoL…)."
    parametres = {"type": "object", "properties": {"nom": {"type": "string", "description": "Nom de l'application ou du jeu."}},
                  "required": ["nom"]}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    def decrire(self, args):
        return f"lancer {args.get('nom')}"

    async def executer(self, ctx: Contexte, nom: str) -> Resultat:
        trouve = await asyncio.to_thread(trouver_application, nom)
        if not trouve:
            return Resultat.echec(f"Je ne trouve pas d'application nommée « {nom} » dans le menu Démarrer.")
        cible, retenu = trouve
        if " --" in cible:  # exécutable avec arguments
            exe, _, args = cible.partition(" --")
            subprocess.Popen([exe, *("--" + args).split()], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        else:
            os.startfile(cible)  # noqa: S606 — lancement voulu
        return Resultat(True, f"{retenu} lancé.", donnees={"cible": cible, "retenu": retenu})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        nom = resultat.donnees["retenu"]
        if _normaliser(nom) not in PROCESSUS:
            return None  # pas de nom de processus connu : invérifiable sans risque de faux négatif
        for _ in range(20):
            if processus_correspondants(nom):
                return True
            await asyncio.sleep(0.5)
        return False


class FermerApplication(Outil):
    nom = "fermer_application"
    description = "Ferme proprement une application ouverte (comme le bouton de fermeture : elle peut proposer d'enregistrer)."
    parametres = {"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    def decrire(self, args):
        return f"fermer {args.get('nom')}"

    async def executer(self, ctx: Contexte, nom: str) -> Resultat:
        processus = processus_correspondants(nom)
        if not processus:
            return Resultat(True, f"{nom} n'était pas ouvert.", donnees={"deja": True})
        noms = sorted({p.info["name"] for p in processus})
        for n in noms:  # fermeture douce (WM_CLOSE), sans /F
            subprocess.run(["taskkill", "/IM", n], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return Resultat(True, f"Demande de fermeture envoyée à {', '.join(noms)}.", donnees={"noms": noms})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        if resultat.donnees.get("deja"):
            return True
        for _ in range(16):
            if not processus_correspondants(args["nom"]):
                return True
            await asyncio.sleep(0.5)
        return False


class Fenetres(Outil):
    nom = "gerer_fenetre"
    description = "Liste les fenêtres ouvertes, ou met une fenêtre au premier plan / la réduit / l'agrandit."
    parametres = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["lister", "premier_plan", "reduire", "agrandir"]},
        "titre": {"type": "string", "description": "Partie du titre de la fenêtre (sauf pour lister)."}},
        "required": ["action"]}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    async def executer(self, ctx: Contexte, action: str, titre: str = "") -> Resultat:
        fenetres = win.fenetres_visibles()
        if action == "lister":
            return Resultat(True, "Fenêtres ouvertes : " + " ; ".join(f["titre"][:60] for f in fenetres[:30]))
        cible = [f for f in fenetres if titre.lower() in f["titre"].lower()]
        if not cible:
            return Resultat.echec(f"Aucune fenêtre dont le titre contient « {titre} ».")
        hwnd = cible[0]["hwnd"]
        if action == "premier_plan":
            win.premier_plan(hwnd)
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 6 if action == "reduire" else 3)
        return Resultat(True, f"{action.replace('_', ' ')} : {cible[0]['titre'][:60]}")


def _volume():
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


class ReglerVolume(Outil):
    nom = "regler_volume"
    description = "Règle le volume général : niveau absolu (0 à 100) ou variation relative, et/ou coupe le son."
    parametres = {"type": "object", "properties": {
        "niveau": {"type": "integer", "minimum": 0, "maximum": 100},
        "variation": {"type": "integer", "minimum": -100, "maximum": 100, "description": "Négatif pour baisser."},
        "muet": {"type": "boolean"}}}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    def decrire(self, args):
        if "niveau" in args:
            return f"mettre le volume à {args['niveau']} %"
        if "variation" in args:
            return f"{'monter' if args['variation'] > 0 else 'baisser'} le volume de {abs(args['variation'])} points"
        return "couper le son" if args.get("muet") else "rétablir le son"

    async def executer(self, ctx: Contexte, niveau: int | None = None, variation: int | None = None,
                       muet: bool | None = None) -> Resultat:
        vol = _volume()
        actuel = round(vol.GetMasterVolumeLevelScalar() * 100)
        if niveau is None and variation is None and muet is None:
            variation = 10
        cible = actuel
        if niveau is not None:
            cible = niveau
        elif variation is not None:
            cible = actuel + variation
        cible = max(0, min(100, cible))
        vol.SetMasterVolumeLevelScalar(cible / 100, None)
        if muet is not None:
            vol.SetMute(int(muet), None)
        elif cible > 0 and vol.GetMute():
            vol.SetMute(0, None)
        return Resultat(True, f"Volume : {actuel} % → {cible} %{' (muet)' if muet else ''}.",
                        donnees={"cible": cible, "muet": muet})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        vol = _volume()
        ok = abs(round(vol.GetMasterVolumeLevelScalar() * 100) - resultat.donnees["cible"]) <= 1
        if resultat.donnees["muet"] is not None:
            ok = ok and bool(vol.GetMute()) == resultat.donnees["muet"]
        return ok


def _peripheriques_sortie() -> list[dict]:
    from pycaw.pycaw import AudioUtilities

    sortie = []
    for d in AudioUtilities.GetAllDevices():
        if d.id and d.id.startswith("{0.0.0.") and str(d.state).endswith("Active"):
            sortie.append({"id": d.id, "nom": d.FriendlyName})
    return sortie


def _definir_sortie_par_defaut(identifiant: str) -> None:
    """IPolicyConfig (interface non documentée mais stable depuis Windows 7)."""
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT

    class IPolicyConfig(comtypes.IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [COMMETHOD([], HRESULT, f"Inutilise{i}") for i in range(10)] + [
            COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], ctypes.c_wchar_p, "id"), (["in"], ctypes.c_int, "role")),
        ]

    politique = comtypes.CoCreateInstance(GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"), IPolicyConfig,
                                          comtypes.CLSCTX_ALL)
    for role in (0, 1, 2):  # console, multimédia, communications
        politique.SetDefaultEndpoint(identifiant, role)


class SortieAudio(Outil):
    nom = "sortie_audio"
    description = "Liste les sorties audio (casque, enceintes, écran) ou change la sortie par défaut."
    parametres = {"type": "object", "properties": {
        "nom": {"type": "string", "description": "Partie du nom de la sortie à activer ; vide pour lister."}}}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    async def executer(self, ctx: Contexte, nom: str = "") -> Resultat:
        sorties = await asyncio.to_thread(_peripheriques_sortie)
        if not nom:
            return Resultat(True, "Sorties audio : " + " ; ".join(s["nom"] for s in sorties), donnees=sorties)
        cible = [s for s in sorties if nom.lower() in s["nom"].lower()]
        if not cible:
            return Resultat.echec(f"Aucune sortie « {nom} ». Disponibles : " + " ; ".join(s["nom"] for s in sorties))
        await asyncio.to_thread(_definir_sortie_par_defaut, cible[0]["id"])
        return Resultat(True, f"Sortie audio : {cible[0]['nom']}.", donnees=cible[0])

    async def verifier(self, ctx, args, resultat) -> bool | None:
        if not args.get("nom"):
            return None
        from pycaw.pycaw import AudioUtilities

        return AudioUtilities.GetSpeakers().id == resultat.donnees["id"]


def _luminosite_ddc(niveau: int) -> int:
    """Écrans externes (DDC/CI via dxva2). Renvoie le nombre d'écrans réglés."""
    from ctypes import wintypes

    class PHYSICAL_MONITOR(ctypes.Structure):
        _fields_ = [("hPhysicalMonitor", wintypes.HANDLE), ("szPhysicalMonitorDescription", wintypes.WCHAR * 128)]

    user32, dxva2 = ctypes.windll.user32, ctypes.windll.dxva2
    moniteurs = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def rappel(hmon, _hdc, _rect, _lp):
        moniteurs.append(hmon)
        return True

    user32.EnumDisplayMonitors(None, None, rappel, 0)
    regles = 0
    for hmon in moniteurs:
        nombre = wintypes.DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(nombre)) or not nombre.value:
            continue
        tableau = (PHYSICAL_MONITOR * nombre.value)()
        if dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, nombre, tableau):
            for pm in tableau:
                if dxva2.SetMonitorBrightness(pm.hPhysicalMonitor, niveau):
                    regles += 1
            dxva2.DestroyPhysicalMonitors(nombre, tableau)
    return regles


class Luminosite(Outil):
    nom = "regler_luminosite"
    description = "Règle la luminosité des écrans (0 à 100)."
    parametres = {"type": "object", "properties": {"niveau": {"type": "integer", "minimum": 0, "maximum": 100}},
                  "required": ["niveau"]}
    niveau = Niveau.REVERSIBLE
    windows_seulement = True

    async def executer(self, ctx: Contexte, niveau: int) -> Resultat:
        regles = await asyncio.to_thread(_luminosite_ddc, niveau)
        if not regles:  # écran intégré (portable) : WMI
            r = await asyncio.to_thread(win.powershell, "(Get-WmiObject -Namespace root/WMI -Class "
                                        f"WmiMonitorBrightnessMethods).WmiSetBrightness(1,{niveau})")
            if r.returncode == 0:
                regles = 1
        if not regles:
            return Resultat.echec("Aucun écran ne permet le réglage logiciel de la luminosité (DDC/CI désactivé ?).")
        return Resultat(True, f"Luminosité réglée à {niveau} % sur {regles} écran(s).")


class Veille(Outil):
    nom = "veille_ou_verrouillage"
    description = "Verrouille la session, ou met le PC en veille."
    parametres = {"type": "object", "properties": {"action": {"type": "string", "enum": ["verrouiller", "veille"]}},
                  "required": ["action"]}
    niveau = Niveau.IRREVERSIBLE  # la veille coupe tout ce qui tourne : confirmation
    windows_seulement = True

    def decrire(self, args):
        return "verrouiller la session" if args.get("action") == "verrouiller" else "mettre le PC en veille"

    async def executer(self, ctx: Contexte, action: str) -> Resultat:
        if action == "verrouiller":
            ctypes.windll.user32.LockWorkStation()
            return Resultat(True, "Session verrouillée.")
        asyncio.get_running_loop().call_later(3, lambda: ctypes.windll.powrprof.SetSuspendState(0, 0, 0))
        return Resultat(True, "Mise en veille dans 3 secondes.")


def etat_gpu() -> dict:
    """Charge 3D et mémoire vidéo dédiée, via les compteurs de performance (classes WMI non traduites)."""
    from jarvis.diagnostic.systeme import _en_liste, powershell_json

    memoire = powershell_json("Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory"
                              " | Select-Object Name,DedicatedUsage")
    moteurs = powershell_json("Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine"
                              " | Where-Object { $_.Name -like '*engtype_3D' } | Select-Object Name,UtilizationPercentage")
    charge: dict[str, int] = {}
    for m in _en_liste(moteurs):
        pid = re.search(r"pid_(\d+)", m.get("Name", ""))
        if pid:
            charge[pid.group(1)] = charge.get(pid.group(1), 0) + int(m.get("UtilizationPercentage") or 0)
    vram = max((int(e.get("DedicatedUsage") or 0) for e in _en_liste(memoire)), default=0)
    return {"charge_3d_pct": min(100, sum(charge.values())), "vram_go": round(vram / 1e9, 1), "par_pid": charge}


def temperatures() -> dict:
    """Températures via LibreHardwareMonitor (s'il tourne, il publie ses capteurs en WMI)."""
    from jarvis.diagnostic.systeme import _en_liste, powershell_json

    capteurs = powershell_json("Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor "
                               "-ErrorAction SilentlyContinue | Where-Object { $_.SensorType -eq 'Temperature' } "
                               "| Select-Object Name,Value,Parent")
    return {c["Name"]: round(float(c["Value"]), 1) for c in _en_liste(capteurs) if c.get("Value") is not None}


class EtatPC(Outil):
    nom = "etat_pc"
    description = "Donne l'état du PC : charge processeur, mémoire, GPU, disques, températures."
    parametres = {"type": "object", "properties": {
        "composant": {"type": "string", "enum": ["cpu", "gpu", "ram", "disque", "temperatures", "tout"]}}}

    async def executer(self, ctx: Contexte, composant: str = "tout") -> Resultat:
        morceaux = []
        donnees: dict = {}
        if composant in ("cpu", "tout"):
            cpu = await asyncio.to_thread(psutil.cpu_percent, 0.5)
            donnees["cpu_pct"] = cpu
            morceaux.append(f"processeur à {cpu:.0f} %")
        if composant in ("ram", "tout"):
            m = psutil.virtual_memory()
            donnees["ram"] = {"utilisee_go": round(m.used / 1e9, 1), "total_go": round(m.total / 1e9, 1)}
            morceaux.append(f"mémoire {m.used / 1e9:.1f} sur {m.total / 1e9:.0f} Go")
        if composant in ("gpu", "tout"):
            g = await asyncio.to_thread(etat_gpu)
            donnees["gpu"] = g
            morceaux.append(f"GPU à {g['charge_3d_pct']} %, {g['vram_go']} Go de mémoire vidéo utilisée")
        if composant in ("disque", "tout"):
            disques = []
            for p in psutil.disk_partitions():
                try:
                    u = psutil.disk_usage(p.mountpoint)
                except OSError:
                    continue
                disques.append(f"{p.mountpoint} {u.free / 1e9:.0f} Go libres sur {u.total / 1e9:.0f}")
            donnees["disques"] = disques
            morceaux.append("disques : " + ", ".join(disques))
        if composant in ("temperatures", "tout", "cpu", "gpu"):
            t = await asyncio.to_thread(temperatures)
            donnees["temperatures"] = t
            if t:
                principales = sorted(t.items(), key=lambda kv: -kv[1])[:4]
                morceaux.append("températures : " + ", ".join(f"{k} {v} °C" for k, v in principales))
            elif composant == "temperatures":
                morceaux.append("températures indisponibles : Windows ne les expose pas sans LibreHardwareMonitor "
                                "(à installer et laisser tourner)")
        return Resultat(True, " ; ".join(morceaux) + ".", donnees=donnees)


class ProcessusGourmands(Outil):
    nom = "processus_gourmands"
    description = "Liste les programmes qui consomment le plus de processeur ou de mémoire."
    parametres = {"type": "object", "properties": {"critere": {"type": "string", "enum": ["cpu", "memoire"]}}}

    async def executer(self, ctx: Contexte, critere: str = "cpu") -> Resultat:
        procs = list(psutil.process_iter(["name", "memory_info"]))
        for p in procs:
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass
        await asyncio.sleep(0.8)
        lignes = []
        for p in procs:
            try:
                lignes.append((p.info["name"], p.cpu_percent(None) / (psutil.cpu_count() or 1),
                               (p.info["memory_info"].rss if p.info["memory_info"] else 0) / 1e9))
            except psutil.Error:
                continue
        lignes.sort(key=lambda l: -(l[1] if critere == "cpu" else l[2]))
        texte = "; ".join(f"{n} {c:.0f} % CPU, {m:.1f} Go" for n, c, m in lignes[:6])
        return Resultat(True, texte)


OUTILS = [LancerApplication, FermerApplication, Fenetres, ReglerVolume, SortieAudio, Luminosite, Veille, EtatPC,
          ProcessusGourmands]
