"""Présence sur le PC (ACC-01) : icône dans la zone de notification, fenêtre flottante, raccourcis globaux.

- Ctrl+Alt+J : appuyer pour parler ; Ctrl+Alt+K : arrêt d'urgence (SEC-07).
- La fenêtre flottante est l'interface web ouverte en mode application (Edge --app), sans barre
  d'adresse, sur 127.0.0.1 avec le jeton local.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import webbrowser

log = logging.getLogger(__name__)


def url_interface(jarvis) -> str:
    return f"http://127.0.0.1:{jarvis.config.serveur.port}/#jeton={jarvis.appareils.jeton_local}"


def ouvrir_fenetre(jarvis) -> None:
    url = url_interface(jarvis)
    edge = shutil.which("msedge") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    try:
        subprocess.Popen([edge, f"--app={url}", "--window-size=460,760"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except OSError:
        webbrowser.open(url)


def _icone():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.ellipse((4, 4, 60, 60), fill=(18, 24, 38, 255), outline=(64, 196, 255, 255), width=4)
    d.ellipse((22, 22, 42, 42), fill=(64, 196, 255, 255))
    return image


def _raccourci_pynput(texte: str) -> str:
    return "+".join(f"<{p}>" if len(p) > 1 else p for p in texte.lower().split("+"))


class Bureau:
    def __init__(self, jarvis, boucle: asyncio.AbstractEventLoop):
        self.jarvis = jarvis
        self.boucle = boucle
        self.icone = None
        self.clavier = None

    def _dans_boucle(self, fonction) -> None:
        self.boucle.call_soon_threadsafe(fonction)

    def parler(self, *_):
        if self.jarvis.boucle:
            self._dans_boucle(self.jarvis.boucle.declencher)

    def arret(self, *_):
        self._dans_boucle(self.jarvis.orchestrateur.arreter_tout)

    def code_appairage(self, *_):
        code = self.jarvis.appareils.nouveau_code()
        self._dans_boucle(lambda: self.jarvis.bus.notifier("Appairage", f"Code à saisir sur l'appareil : {code} "
                                                                        "(valable 5 minutes)", urgent=False))
        if self.icone:
            self.icone.notify(f"Code d'appairage : {code}", "Jarvis")

    def quitter(self, *_):
        if self.icone:
            self.icone.stop()
        if self.clavier:
            self.clavier.stop()
        self.boucle.call_soon_threadsafe(lambda: asyncio.ensure_future(self.jarvis.arreter()))

    def demarrer(self) -> None:
        import pystray
        from pynput import keyboard

        v = self.jarvis.config.voix
        try:
            self.clavier = keyboard.GlobalHotKeys({_raccourci_pynput(v.raccourci_parler): self.parler,
                                                   _raccourci_pynput(v.raccourci_arret): self.arret})
            self.clavier.start()
        except Exception:  # noqa: BLE001
            log.exception("Raccourcis globaux indisponibles")
        menu = pystray.Menu(
            pystray.MenuItem("Ouvrir Jarvis", lambda *_: ouvrir_fenetre(self.jarvis), default=True),
            pystray.MenuItem("Parler (Ctrl+Alt+J)", self.parler),
            pystray.MenuItem("Arrêt d'urgence (Ctrl+Alt+K)", self.arret),
            pystray.MenuItem("Appairer un appareil…", self.code_appairage),
            pystray.MenuItem("Quitter", self.quitter),
        )
        self.icone = pystray.Icon("jarvis", _icone(), "Jarvis", menu)
        threading.Thread(target=self.icone.run, daemon=True, name="icone").start()
