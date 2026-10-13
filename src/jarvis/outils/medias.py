"""OUT-MED : lecture / pause / suivant (touches multimédia, valables pour Spotify, navigateur, VLC…),
recherche et lecture Spotify (API officielle, compte branché par Mathieu), musique locale en repli.

Spotify : `python -m jarvis connecter spotify` (PKCE, aucun secret applicatif). Le contrôle de la
lecture par l'API exige un compte Premium ; sans compte branché, Jarvis ouvre la recherche Spotify.
Les requêtes partent vers api.spotify.com (le service de musique), jamais vers une IA.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from pathlib import Path

from jarvis.outils import windows as win
from jarvis.outils.base import Contexte, Niveau, Outil, Resultat

HOTES_SPOTIFY = ("api.spotify.com", "accounts.spotify.com")
REDIRECTION = "http://127.0.0.1:8730/connecter/spotify"
PORTEES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private"
EXTENSIONS_AUDIO = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus"}


# --- Spotify --------------------------------------------------------------------------------


def lien_connexion_spotify(client_id: str) -> tuple[str, str]:
    """URL d'autorisation PKCE et vérificateur à conserver jusqu'au retour."""
    verificateur = secrets.token_urlsafe(64)[:96]
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).decode().rstrip("=")
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": REDIRECTION, "scope": PORTEES,
              "code_challenge_method": "S256", "code_challenge": defi}
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params), verificateur


class Spotify:
    def __init__(self, ctx: Contexte):
        self.ctx = ctx
        self.coffre = ctx.coffre

    @property
    def configure(self) -> bool:
        return bool(self.coffre and self.coffre.lire("spotify_refresh") and self.coffre.lire("spotify_client_id"))

    async def _jeton(self) -> str:
        expire = float(self.coffre.lire("spotify_expire") or 0)
        if expire > time.time() + 30:
            return self.coffre.lire("spotify_acces")
        r = await self.ctx.http("POST", "https://accounts.spotify.com/api/token", data={
            "grant_type": "refresh_token", "refresh_token": self.coffre.lire("spotify_refresh"),
            "client_id": self.coffre.lire("spotify_client_id")})
        r.raise_for_status()
        d = r.json()
        self.coffre.ecrire("spotify_acces", d["access_token"])
        self.coffre.ecrire("spotify_expire", str(time.time() + d.get("expires_in", 3600)))
        if d.get("refresh_token"):
            self.coffre.ecrire("spotify_refresh", d["refresh_token"])
        return d["access_token"]

    async def api(self, methode: str, chemin: str, **kwargs):
        jeton = await self._jeton()
        r = await self.ctx.http(methode, "https://api.spotify.com/v1" + chemin,
                                headers={"Authorization": f"Bearer {jeton}"}, **kwargs)
        if r.status_code == 204 or not r.content:
            return {}
        if r.status_code >= 400:
            raise RuntimeError(f"Spotify {r.status_code} : {r.text[:200]}")
        return r.json()


async def echanger_code_spotify(ctx: Contexte, code: str, verificateur: str, client_id: str) -> None:
    r = await ctx.http("POST", "https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECTION,
        "client_id": client_id, "code_verifier": verificateur})
    r.raise_for_status()
    d = r.json()
    ctx.coffre.ecrire("spotify_client_id", client_id)
    ctx.coffre.ecrire("spotify_acces", d["access_token"])
    ctx.coffre.ecrire("spotify_refresh", d["refresh_token"])
    ctx.coffre.ecrire("spotify_expire", str(time.time() + d.get("expires_in", 3600)))


# --- Musique locale -------------------------------------------------------------------------


def chercher_musique_locale(recherche: str, n: int = 50) -> list[Path]:
    mots = [m for m in recherche.lower().split() if len(m) > 1]
    trouves = []
    for racine in [Path.home() / "Music", Path.home() / "Musique"]:
        if not racine.exists():
            continue
        for dossier, _, fichiers in os.walk(racine):
            for f in fichiers:
                chemin = Path(dossier) / f
                if chemin.suffix.lower() in EXTENSIONS_AUDIO and all(m in str(chemin).lower() for m in mots):
                    trouves.append(chemin)
                    if len(trouves) >= n:
                        return trouves
    return trouves


# --- Outils ---------------------------------------------------------------------------------


class ControleMedia(Outil):
    nom = "controle_media"
    description = "Contrôle la lecture en cours (Spotify, navigateur, lecteur local) : lecture/pause, suivant, précédent."
    parametres = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["lecture", "pause", "suivant", "precedent", "stop"]}},
        "required": ["action"]}
    niveau = Niveau.REVERSIBLE
    hotes = HOTES_SPOTIFY
    windows_seulement = True

    def decrire(self, args):
        return {"lecture": "reprendre la lecture", "pause": "mettre en pause", "suivant": "passer au morceau suivant",
                "precedent": "revenir au morceau précédent", "stop": "arrêter la lecture"}[args["action"]]

    async def executer(self, ctx: Contexte, action: str) -> Resultat:
        spotify = Spotify(ctx)
        if spotify.configure:  # l'API distingue lecture et pause (la touche multimédia bascule)
            try:
                chemins_api = {"lecture": ("PUT", "/me/player/play"), "pause": ("PUT", "/me/player/pause"),
                               "suivant": ("POST", "/me/player/next"), "precedent": ("POST", "/me/player/previous"),
                               "stop": ("PUT", "/me/player/pause")}
                await spotify.api(*chemins_api[action])
                return Resultat(True, f"Spotify : {self.decrire({'action': action})}.", donnees={"spotify": True})
            except Exception:  # noqa: BLE001 — repli sur les touches multimédia
                pass
        touche = {"lecture": win.VK_MEDIA_PLAY_PAUSE, "pause": win.VK_MEDIA_PLAY_PAUSE, "suivant": win.VK_MEDIA_NEXT,
                  "precedent": win.VK_MEDIA_PREV, "stop": win.VK_MEDIA_STOP}[action]
        win.appuyer_touche(touche)
        return Resultat(True, f"Touche multimédia envoyée ({action}).")

    async def verifier(self, ctx, args, resultat) -> bool | None:
        if not (resultat.donnees or {}).get("spotify") or args["action"] not in ("lecture", "pause"):
            return None
        await asyncio.sleep(0.8)
        etat = await Spotify(ctx).api("GET", "/me/player")
        return bool(etat.get("is_playing")) == (args["action"] == "lecture")


class JouerMusique(Outil):
    nom = "jouer_musique"
    description = "Lance un artiste, un album, un titre ou une playlist (Spotify, sinon musique locale)."
    parametres = {"type": "object", "properties": {
        "recherche": {"type": "string"},
        "type": {"type": "string", "enum": ["titre", "artiste", "album", "playlist"], "description": "Facultatif."}},
        "required": ["recherche"]}
    niveau = Niveau.REVERSIBLE
    hotes = HOTES_SPOTIFY

    def decrire(self, args):
        return f"jouer {args.get('recherche')}"

    async def executer(self, ctx: Contexte, recherche: str, type: str = "") -> Resultat:  # noqa: A002
        spotify = Spotify(ctx)
        if spotify.configure:
            types_api = {"titre": "track", "artiste": "artist", "album": "album", "playlist": "playlist"}
            cherche = types_api.get(type, "track,artist,playlist")
            res = await spotify.api("GET", "/search", params={"q": recherche, "type": cherche, "limit": 3, "market": "FR"})
            corps = None
            libelle = ""
            for cle in ("playlists", "artists", "albums", "tracks") if type != "titre" else ("tracks",):
                items = [i for i in (res.get(cle) or {}).get("items", []) if i]
                if items:
                    item = items[0]
                    libelle = item["name"]
                    corps = {"uris": [item["uri"]]} if cle == "tracks" else {"context_uri": item["uri"]}
                    break
            if corps is None:
                return Resultat.echec(f"Rien trouvé sur Spotify pour « {recherche} ».")
            try:
                await spotify.api("PUT", "/me/player/play", json=corps)
            except RuntimeError as e:
                if "404" in str(e):
                    return Resultat.echec("Aucun appareil Spotify actif : ouvre Spotify puis redemande.")
                raise
            return Resultat(True, f"Lecture Spotify : {libelle}.")
        locaux = await asyncio.to_thread(chercher_musique_locale, recherche)
        if locaux:
            liste = Path(os.environ.get("TEMP", ".")) / "jarvis-lecture.m3u"
            liste.write_text("\n".join(str(p) for p in locaux), "utf-8")
            os.startfile(str(liste))  # noqa: S606
            return Resultat(True, f"Lecture de {len(locaux)} morceau(x) local(aux) correspondant à « {recherche} ».")
        os.startfile("spotify:search:" + urllib.parse.quote(recherche))  # noqa: S606
        return Resultat(True, f"Spotify n'est pas branché à Jarvis : j'ai ouvert la recherche « {recherche} » dans "
                              "Spotify, il reste à lancer la lecture.")


class MorceauEnCours(Outil):
    nom = "morceau_en_cours"
    description = "Dit quel morceau est en train de jouer sur Spotify."
    hotes = HOTES_SPOTIFY

    async def executer(self, ctx: Contexte) -> Resultat:
        spotify = Spotify(ctx)
        if not spotify.configure:
            return Resultat.echec("Spotify n'est pas branché à Jarvis.")
        etat = await spotify.api("GET", "/me/player/currently-playing")
        item = (etat or {}).get("item")
        if not item:
            return Resultat(True, "Rien ne joue en ce moment.")
        artistes = ", ".join(a["name"] for a in item.get("artists", []))
        return Resultat(True, f"{item['name']} de {artistes}.")


OUTILS = [ControleMedia, JouerMusique, MorceauEnCours]
