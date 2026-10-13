"""Agent Jarvis pour macOS.

    python -m jarvis.mac appairer https://<pc>.<tailnet>.ts.net 123456
    python -m jarvis.mac                     # icône dans la barre des menus, ⌥⌘J pour parler
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading

from jarvis.mac import agent as module_agent


def demarrer() -> int:
    import rumps
    from pynput import keyboard

    identifiants = module_agent.lire_trousseau()
    if not identifiants:
        print("Mac non appairé : python -m jarvis.mac appairer <adresse du PC> <code>")
        return 1
    serveur, jeton = identifiants
    boucle = asyncio.new_event_loop()
    agent = module_agent.AgentMac(serveur, jeton)
    threading.Thread(target=lambda: (asyncio.set_event_loop(boucle), boucle.run_until_complete(agent.boucle())),
                     daemon=True, name="jarvis-connexion").start()
    appuye = threading.Event()

    def executer(coro):
        return asyncio.run_coroutine_threadsafe(coro, boucle)

    def parler():
        if appuye.is_set():
            return
        appuye.set()

        def enregistrer():
            son = module_agent.enregistrer_tant_que(appuye.is_set)
            try:
                _, reponse = executer(agent.parler(son)).result(180)
                module_agent.notifier_mac("Jarvis", reponse)
            except Exception as e:  # noqa: BLE001
                module_agent.notifier_mac("Jarvis", f"Erreur : {e}")

        threading.Thread(target=enregistrer, daemon=True).start()

    def relache(touche):
        if appuye.is_set() and touche in (keyboard.Key.cmd, keyboard.Key.alt, keyboard.KeyCode.from_char("j")):
            appuye.clear()

    raccourci = keyboard.HotKey(keyboard.HotKey.parse("<cmd>+<alt>+j"), parler)
    ecouteur = keyboard.Listener(on_press=lambda t: raccourci.press(ecouteur.canonical(t)),
                                 on_release=lambda t: (raccourci.release(ecouteur.canonical(t)), relache(t)))
    ecouteur.start()

    class Application(rumps.App):
        def __init__(self):
            super().__init__("Jarvis", title="◉", quit_button=None)
            self.menu = ["Écrire à Jarvis…", "Ouvrir l'interface", None, "État", None, "Quitter"]
            self.timer = rumps.Timer(self.actualiser, 5)
            self.timer.start()

        def actualiser(self, _):
            self.title = "◉" if agent.connecte else ("◌" if agent.en_secours else "…")
            self.menu["État"].title = ("Connecté au PC" if agent.connecte else
                                       "Mode secours (PC injoignable)" if agent.en_secours else "Connexion…")

        @rumps.clicked("Écrire à Jarvis…")
        def ecrire(self, _):
            fenetre = rumps.Window("Que veux-tu demander à Jarvis ?", "Jarvis", ok="Envoyer", cancel="Annuler",
                                   dimensions=(360, 80))
            r = fenetre.run()
            if r.clicked and r.text.strip():
                try:
                    reponse = executer(agent.demander(r.text.strip())).result(240)
                except Exception as e:  # noqa: BLE001
                    reponse = f"Erreur : {e}"
                rumps.alert("Jarvis", reponse[:1500])

        @rumps.clicked("Ouvrir l'interface")
        def interface(self, _):
            import webbrowser

            webbrowser.open(serveur)

        @rumps.clicked("Quitter")
        def quitter(self, _):
            rumps.quit_application()

    Application().run()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    if argv[:1] == ["appairer"]:
        if len(argv) != 3:
            print(__doc__)
            return 1
        module_agent.appairer(argv[1], argv[2])
        print("Mac appairé ; jeton rangé dans le Trousseau.")
        return 0
    return demarrer()


if __name__ == "__main__":
    sys.exit(main())
