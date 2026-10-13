"""Agent macOS (lot J14) : client vocal et texte, « mains » du Mac pour le cerveau du PC, secours.

- MAC-01 : connexion persistante au PC via Tailscale, jeton propre au Mac (dans le Trousseau).
- MAC-02 : icône de la barre des menus, raccourci ⌥⌘J (appuyer pour parler), saisie de texte.
- MAC-03/05 : outils du Mac déclarés au registre du PC, mêmes niveaux de permission.
- MAC-04 / MULTI-06 : PC injoignable → mode secours local, annoncé.
- SEC-14 : garde réseau active ; seul le PC Jarvis est joignable.
- PERF-12 : au repos, une connexion WebSocket et une icône (< 1 % CPU, < 200 Mo).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from jarvis.mac import outils_mac
from jarvis.securite.reseau import GARDE

log = logging.getLogger(__name__)
SERVICE_TROUSSEAU = "jarvis-jeton"
DELAI_SECOURS_S = 30


# --- Trousseau macOS (SEC-05) ---------------------------------------------------------------


def lire_trousseau() -> tuple[str, str] | None:
    r = subprocess.run(["security", "find-generic-password", "-s", SERVICE_TROUSSEAU, "-g", "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0 or "|" not in r.stdout:
        return None
    serveur, _, jeton = r.stdout.strip().partition("|")
    return serveur, jeton


def ecrire_trousseau(serveur: str, jeton: str) -> None:
    subprocess.run(["security", "add-generic-password", "-a", "jarvis", "-s", SERVICE_TROUSSEAU, "-U", "-w",
                    f"{serveur}|{jeton}"], check=True, capture_output=True)


def appairer(serveur: str, code: str) -> str:
    serveur = serveur.rstrip("/")
    r = httpx.post(f"{serveur}/api/appairer", json={"code": code, "nom": "Mac", "type": "mac"}, timeout=20)
    r.raise_for_status()
    jeton = r.json()["jeton"]
    ecrire_trousseau(serveur, jeton)
    return jeton


def notifier_mac(titre: str, texte: str) -> None:
    script = f"display notification {outils_mac.echapper(texte[:240])} with title {outils_mac.echapper(titre)}"
    subprocess.run(["osascript", "-e", script], capture_output=True)


# --- Agent ----------------------------------------------------------------------------------


class AgentMac:
    def __init__(self, serveur: str, jeton: str):
        self.serveur, self.jeton = serveur.rstrip("/"), jeton
        self.ident = jeton.partition(".")[0]
        self.ws = None
        self.connecte = False
        self.dernier_contact = 0.0
        self.secours = None
        self._reponse: asyncio.Future | None = None
        self._texte_reponse = ""
        GARDE.hotes_globaux = (urlparse(self.serveur).hostname or "",)
        GARDE.installer()

    @property
    def en_secours(self) -> bool:
        return not self.connecte and time.monotonic() - self.dernier_contact > DELAI_SECOURS_S

    def _entetes(self) -> dict:
        return {"Authorization": f"Bearer {self.jeton}"}

    async def boucle(self) -> None:
        import websockets

        url = self.serveur.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
        delai = 1.0
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, max_size=2**22) as ws:
                    await ws.send(json.dumps({"jeton": self.jeton}))
                    self.ws, self.connecte, delai = ws, True, 1.0
                    async for brut in ws:
                        self.dernier_contact = time.monotonic()
                        await self._traiter(json.loads(brut))
            except Exception as e:  # noqa: BLE001
                log.info("Connexion au PC perdue : %s", e)
            self.ws, self.connecte = None, False
            await asyncio.sleep(delai)
            delai = min(delai * 2, 30)

    async def envoyer(self, message: dict) -> None:
        if self.ws is not None:
            await self.ws.send(json.dumps(message, ensure_ascii=False))

    async def _traiter(self, m: dict) -> None:
        d = m.get("donnees") or {}
        t = m.get("type")
        if t == "bienvenue":
            await self.envoyer({"type": "outils", "outils": outils_mac.DEFINITIONS})
        elif t == "executer":
            ok, message = await asyncio.to_thread(outils_mac.executer, d.get("outil", ""), d.get("args") or {},
                                                 self.vision_par_pc)
            await self.envoyer({"type": "resultat", "donnees": {"id": d.get("id"), "ok": ok, "message": message}})
        elif t == "notification":
            notifier_mac(d.get("titre", "Jarvis"), d.get("texte", ""))
            await self.envoyer({"type": "lu", "id": d.get("id_notification", "")})
        elif t == "confirmation" and d.get("appareil") in (self.ident, "pc"):
            asyncio.create_task(self._confirmer(d))
        elif t == "recevoir":
            await asyncio.to_thread(self._recevoir, d)
        elif t == "morceau" and self._reponse is not None:
            self._texte_reponse += d.get("texte", "")
        elif t == "fin" and self._reponse is not None and not self._reponse.done():
            self._reponse.set_result(self._texte_reponse)

    async def _confirmer(self, d: dict) -> None:
        from jarvis.mac.secours import ConfirmateurDialogue

        oui = await ConfirmateurDialogue().question(d.get("question", ""))
        await self.envoyer({"type": "confirmer", "id": d.get("id"), "oui": oui})

    def _recevoir(self, d: dict) -> None:
        nature = d.get("nature")
        if nature == "lien":
            subprocess.run(["open", d.get("contenu", "")])
        elif nature == "texte":
            subprocess.run(["pbcopy"], input=d.get("contenu", "").encode())
            notifier_mac("Jarvis", "Texte reçu (copié)")
        elif nature == "fichier":
            r = httpx.get(self.serveur + d["url"], headers=self._entetes(), timeout=120)
            if r.status_code == 200:
                cible = Path.home() / "Downloads" / Path(d.get("nom", "fichier")).name
                cible.write_bytes(r.content)
                notifier_mac("Fichier reçu", cible.name)
        elif nature == "sonner":
            outils_mac.executer("sonner", {})

    def vision_par_pc(self, png: bytes, question: str) -> str:
        r = httpx.post(f"{self.serveur}/api/vision", headers=self._entetes(), timeout=180,
                       files={"image": ("ecran.png", png, "image/png")}, data={"question": question})
        r.raise_for_status()
        return r.json()["analyse"]

    # --- Demandes de Mathieu --------------------------------------------------------------

    async def demander(self, texte: str) -> str:
        if self.connecte:
            self._reponse = asyncio.get_running_loop().create_future()
            self._texte_reponse = ""
            await self.envoyer({"type": "texte", "texte": texte})
            try:
                return await asyncio.wait_for(self._reponse, 180)
            finally:
                self._reponse = None
        return await self._secours().repondre(texte)

    def _secours(self):
        if self.secours is None:
            from jarvis.mac.secours import Secours

            self.secours = Secours()
            asyncio.create_task(self.secours.surveiller())
        return self.secours

    async def parler(self, son_wav: bytes) -> tuple[str, str]:
        """Appuyer pour parler : audio → PC (transcription + réponse + voix) ; secours si injoignable."""
        if self.connecte:
            async with httpx.AsyncClient(timeout=120) as http:
                r = await http.post(f"{self.serveur}/api/audio", headers=self._entetes(),
                                    files={"fichier": ("parole.wav", son_wav, "audio/wav")})
            r.raise_for_status()
            d = r.json()
            if d.get("audio_wav_b64"):
                jouer_wav(base64.b64decode(d["audio_wav_b64"]))
            return d.get("transcription", ""), d.get("reponse", "")
        return "", f"{_secours_prefixe()}La voix exige le PC ; écris-moi ta demande."


def _secours_prefixe() -> str:
    from jarvis.mac.secours import PREFIXE

    return PREFIXE


def jouer_wav(donnees: bytes) -> None:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(donnees)
    subprocess.Popen(["afplay", f.name])


def enregistrer_tant_que(appuye) -> bytes:
    """Enregistre le micro tant que `appuye()` est vrai ; renvoie un WAV 16 kHz mono."""
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    blocs = []
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32") as flux:
        while appuye() and len(blocs) < 16000 * 30 // 1600:
            bloc, _ = flux.read(1600)
            blocs.append(bloc[:, 0].copy())
    tampon = io.BytesIO()
    sf.write(tampon, np.concatenate(blocs) if blocs else np.zeros(1600, np.float32), 16000, format="WAV")
    return tampon.getvalue()
