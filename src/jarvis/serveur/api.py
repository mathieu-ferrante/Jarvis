"""API locale et interface web (lot J5) : PC, téléphone, Mac.

- Écoute uniquement sur 127.0.0.1. L'accès depuis les autres appareils passe par
  `tailscale serve` (HTTPS, réseau privé Tailscale), jamais par un port ouvert sur Internet.
- Chaque requête porte le jeton d'un appareil appairé (SEC-06, SEC-10), révocable (SEC-13).
- WebSocket `/ws` : discussion en texte (VOX-06), évènements en direct (états, notifications,
  confirmations à valider d'un clic).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

log = logging.getLogger(__name__)
DOSSIER_WEB = Path(__file__).resolve().parents[3] / "web" / "dist"
TYPES_PUBLIES = {"notification", "confirmation", "reponse", "demande", "action", "tache", "arret", "pret", "souvenir",
                 "pensee", "voix_etat", "voix_transcription", "voix_reponse", "voix_latence", "jeu", "briefing"}


def decoder_audio(donnees: bytes) -> np.ndarray:
    """Audio envoyé par le téléphone (webm/opus, ogg, wav, m4a) → 16 kHz mono float32, via PyAV."""
    import av

    sortie = []
    with av.open(io.BytesIO(donnees)) as conteneur:
        reechantillonneur = av.AudioResampler(format="flt", layout="mono", rate=16000)
        for trame in conteneur.decode(audio=0):
            for t in reechantillonneur.resample(trame):
                sortie.append(t.to_ndarray().reshape(-1))
        for t in reechantillonneur.resample(None):
            sortie.append(t.to_ndarray().reshape(-1))
    return np.concatenate(sortie).astype(np.float32) if sortie else np.zeros(0, np.float32)


def encoder_wav(son: np.ndarray, taux: int) -> bytes:
    import soundfile as sf

    tampon = io.BytesIO()
    sf.write(tampon, son, taux, format="WAV", subtype="PCM_16")
    return tampon.getvalue()


def creer_app(jarvis) -> FastAPI:
    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None, openapi_url=None)
    clients: set[WebSocket] = set()
    verrous_spotify: dict[str, tuple[str, str]] = {}
    moteurs_audio: dict = {}

    def appareil(authorization: str | None = Header(default=None)) -> dict:
        jeton = (authorization or "").removeprefix("Bearer ").strip()
        a = jarvis.appareils.authentifier(jeton)
        if not a:
            raise HTTPException(401, "Appareil non appairé")
        return a

    # --- Diffusion des évènements -----------------------------------------------------------

    async def diffuser(evt) -> None:
        if evt.type not in TYPES_PUBLIES:
            return
        if evt.type == "notification" and getattr(jarvis, "multi", None) is not None:
            # MULTI-05 : appareil actif d'abord, les autres seulement si elle n'est pas lue
            await jarvis.multi.notifier({"type": evt.type, "donnees": evt.donnees, "horodatage": evt.horodatage})
            return
        message = json.dumps({"type": evt.type, "donnees": evt.donnees, "horodatage": evt.horodatage},
                             ensure_ascii=False, default=str)
        for ws in list(clients):
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                clients.discard(ws)

    jarvis.bus.abonner(diffuser)

    # --- Appairage --------------------------------------------------------------------------

    @app.post("/api/appairer")
    async def appairer(corps: dict):
        jeton = jarvis.appareils.appairer(str(corps.get("code", "")), str(corps.get("nom", "appareil")),
                                          str(corps.get("type", "navigateur")))
        if not jeton:
            raise HTTPException(403, "Code invalide ou expiré")
        jarvis.bus.notifier("Nouvel appareil", f"{corps.get('nom')} est appairé.")
        return {"jeton": jeton}

    @app.post("/api/appareils/code")
    async def nouveau_code(a: dict = Depends(appareil)):
        if a["id"] != "pc":
            raise HTTPException(403, "Seul le PC peut générer un code d'appairage")
        return {"code": jarvis.appareils.nouveau_code(), "valide_s": 300}

    @app.get("/api/appareils")
    async def appareils(a: dict = Depends(appareil)):
        return {"appareils": jarvis.appareils.lister(), "actif": jarvis.appareils.appareil_actif(), "moi": a["id"]}

    @app.delete("/api/appareils/{ident}")
    async def revoquer(ident: str, a: dict = Depends(appareil)):
        if not jarvis.appareils.revoquer(ident):
            raise HTTPException(404)
        for ws in list(clients):  # SEC-13 : coupe aussitôt les connexions de l'appareil révoqué
            if getattr(ws.state, "appareil", None) == ident:
                await ws.close(code=4401)
        return {"ok": True}

    # --- Discussion -------------------------------------------------------------------------

    @app.post("/api/message")
    async def message(corps: dict, a: dict = Depends(appareil)):
        texte = str(corps.get("texte", "")).strip()
        if not texte:
            raise HTTPException(400, "Message vide")
        debut = time.perf_counter()
        reponse = await jarvis.orchestrateur.repondre_texte(texte, canal="texte",
                                                            conversation=corps.get("conversation", "principale"),
                                                            origine=f"texte:{a['id']}")
        jarvis.metriques.ajouter(canal="texte", texte=texte, total_ms=round(1000 * (time.perf_counter() - debut)))
        return {"reponse": reponse}

    def _moteurs():
        if not moteurs_audio:
            from jarvis.voix import moteurs

            if jarvis.boucle is not None:
                moteurs_audio.update(stt=jarvis.boucle.stt, tts=jarvis.boucle.tts)
            else:
                moteurs_audio.update(stt=moteurs.creer_transcripteur(jarvis.config.voix),
                                     tts=moteurs.Synthese(jarvis.config.voix.tts))
        return moteurs_audio

    @app.post("/api/audio")
    async def audio(fichier: UploadFile = File(...), voix: bool = True, a: dict = Depends(appareil)):
        """Appui pour parler depuis le téléphone : audio → transcription → réponse (texte + voix)."""
        debut = time.perf_counter()
        son = await asyncio.to_thread(decoder_audio, await fichier.read())
        m = await asyncio.to_thread(_moteurs)
        from jarvis.voix.boucle import retirer_mot_reveil

        texte = retirer_mot_reveil(await asyncio.to_thread(m["stt"].transcrire, son))
        t_stt = time.perf_counter()
        if not texte:
            return {"transcription": "", "reponse": "Je n'ai rien entendu."}
        reponse = await jarvis.orchestrateur.repondre_texte(texte, canal="voix", origine=f"voix:{a['id']}")
        resultat = {"transcription": texte, "reponse": reponse}
        if voix and reponse:
            from jarvis.voix.phrases import pour_la_voix

            son_reponse, taux = await asyncio.to_thread(m["tts"].synthetiser, pour_la_voix(reponse))
            resultat["audio_wav_b64"] = __import__("base64").b64encode(encoder_wav(son_reponse, taux)).decode()
        jarvis.metriques.ajouter(canal=f"voix:{a['id']}", texte=texte,
                                 transcription_ms=round(1000 * (t_stt - debut)),
                                 total_ms=round(1000 * (time.perf_counter() - debut)))
        return resultat

    @app.post("/api/confirmation/{ident}")
    async def confirmer(ident: int, corps: dict, a: dict = Depends(appareil)):
        oui = bool(corps.get("oui"))
        demande = jarvis.confirmateur.demandes.get(ident)
        if demande is not None and not demande.peut_confirmer(a["id"]):
            raise HTTPException(403, "Seul l'appareil à l'origine de la demande (ou le PC) peut la confirmer (SEC-12)")
        if oui and a.get("type") == "android" and not corps.get("biometrie"):
            raise HTTPException(403, "Action irréversible depuis le téléphone : empreinte requise (SEC-12)")
        if not jarvis.confirmateur.repondre(ident, oui):
            raise HTTPException(404, "Demande expirée")
        return {"ok": True}

    @app.post("/api/arret")
    async def arret(a: dict = Depends(appareil)):
        jarvis.orchestrateur.arreter_tout()
        return {"ok": True}

    @app.post("/api/parler")
    async def parler(a: dict = Depends(appareil)):
        """Appuyer pour parler sur le PC (bouton de l'interface)."""
        if jarvis.boucle is None:
            raise HTTPException(503, "Voix indisponible")
        jarvis.boucle.declencher()
        return {"ok": True}

    # --- Consultation -----------------------------------------------------------------------

    @app.get("/api/etat")
    async def etat(a: dict = Depends(appareil)):
        import psutil

        from jarvis.outils.systeme import etat_gpu

        gpu = await asyncio.to_thread(etat_gpu) if jarvis.config.jeu.detection else {}
        return {"pret": jarvis.metriques.pret, "demarrage_s": jarvis.metriques.demarrage_s,
                "modele": jarvis.config.llm.principal, "en_jeu": jarvis.etat_jeu,
                "voix": jarvis.boucle.etat if jarvis.boucle else "indisponible",
                "cpu_pct": psutil.cpu_percent(None), "ram_pct": psutil.virtual_memory().percent,
                "gpu": {k: v for k, v in gpu.items() if k != "par_pid"},
                "echanges": jarvis.metriques.echanges[-30:], "refus_reseau": __import__(
                    "jarvis.securite.reseau", fromlist=["GARDE"]).GARDE.refus[-20:]}

    @app.get("/api/journal")
    async def journal(n: int = 100, a: dict = Depends(appareil)):
        return {"actions": jarvis.journal.dernieres(min(n, 500))}

    @app.get("/api/memoire")
    async def memoire(q: str = "", a: dict = Depends(appareil)):
        faits = jarvis.memoire.lister(q or None, 100)
        return {"faits": [{k: v for k, v in f.items() if k != "vecteur"} for f in faits],
                "statistiques": jarvis.memoire.statistiques()}

    @app.delete("/api/memoire/{ident}")
    async def oublier(ident: int, a: dict = Depends(appareil)):
        if not jarvis.memoire.oublier(ident):
            raise HTTPException(404)
        jarvis.journal.consigner(outil="oublier", arguments={"id": ident}, niveau="irreversible",
                                 decision="confirmee", demande="clic dans l'interface", origine=f"interface:{a['id']}",
                                 ok=True)
        return {"ok": True}

    @app.put("/api/memoire/{ident}")
    async def corriger(ident: int, corps: dict, a: dict = Depends(appareil)):
        if not jarvis.memoire.corriger(ident, str(corps.get("texte", ""))):
            raise HTTPException(404)
        return {"ok": True}

    @app.get("/api/historique")
    async def historique(q: str = "", n: int = 50, a: dict = Depends(appareil)):
        lignes = jarvis.memoire.chercher_historique(q, n) if q else jarvis.memoire.historique(n)
        return {"echanges": lignes}

    @app.get("/api/rappels")
    async def rappels(a: dict = Depends(appareil)):
        return {"rappels": jarvis.rappels.lister(), "taches": jarvis.services["taches"].liste()}

    @app.get("/api/notifications")
    async def notifications(a: dict = Depends(appareil)):
        return {"notifications": [{"type": e.type, "donnees": e.donnees, "horodatage": e.horodatage}
                                  for e in jarvis.bus.historique if e.type == "notification"][-50:]}

    @app.post("/api/vision")
    async def vision(image: UploadFile = File(...), question: str = "Décris ce qui est affiché.",
                     a: dict = Depends(appareil)):
        """Analyse d'une capture envoyée par un appareil (écran du Mac) par le modèle de vision du PC."""
        from jarvis.outils.base import Contexte
        from jarvis.outils.vision import interroger_vision

        ctx = Contexte(config=jarvis.config, services=jarvis.services)
        try:
            analyse = await interroger_vision(ctx, await image.read(), question)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"Vision indisponible : {e}") from e
        return {"analyse": analyse}

    @app.get("/api/modeles/reveil/{nom}")
    async def modele_reveil(nom: str, a: dict = Depends(appareil)):
        """Modèles openWakeWord pour le mot de réveil du téléphone (TEL-02) : servis par le PC, pas par Internet."""
        from jarvis import modeles
        from jarvis.diagnostic.catalogue import OPENWAKEWORD

        par_nom = {f.nom: f for f in OPENWAKEWORD.values()}
        if nom not in par_nom or not modeles.chemin(par_nom[nom]).exists():
            raise HTTPException(404)
        return FileResponse(modeles.chemin(par_nom[nom]))

    @app.post("/api/reveil/verifier")
    async def verifier_reveil(request: Request, a: dict = Depends(appareil)):
        """Second étage du mot de réveil du téléphone : « Jarvis » est-il dans ces 1,6 s (PCM 16 kHz) ?"""
        from jarvis.voix.moteurs import contient_jarvis

        brut = await request.body()
        if len(brut) > 16000 * 2 * 3:
            raise HTTPException(413)
        son = np.frombuffer(brut, dtype="<i2").astype(np.float32) / 32768
        texte = await asyncio.to_thread(_moteurs()["stt"].transcrire, son)
        return {"jarvis": contient_jarvis(texte), "texte": texte}

    @app.get("/api/fichiers/{jeton}")
    async def fichier_partage(jeton: str, a: dict = Depends(appareil)):
        """Fichier envoyé par Jarvis vers cet appareil (lien à usage unique, 10 minutes)."""
        chemin = jarvis.multi.fichier_pour_lien(jeton) if getattr(jarvis, "multi", None) else None
        if chemin is None:
            raise HTTPException(404, "Lien expiré ou déjà utilisé")
        return FileResponse(chemin, filename=chemin.name)

    # --- Spotify (compte branché par Mathieu) -----------------------------------------------

    @app.post("/api/connecter/spotify")
    async def connecter_spotify(corps: dict, a: dict = Depends(appareil)):
        from jarvis.outils.medias import lien_connexion_spotify

        client_id = str(corps.get("client_id", "")).strip()
        if not client_id:
            raise HTTPException(400, "client_id requis (application créée sur developer.spotify.com)")
        lien, verificateur = lien_connexion_spotify(client_id)
        verrous_spotify["courant"] = (verificateur, client_id)
        return {"lien": lien}

    @app.get("/connecter/spotify", response_class=HTMLResponse)
    async def retour_spotify(code: str = "", request: Request = None):
        from jarvis.outils.base import Contexte
        from jarvis.outils.medias import ControleMedia, echanger_code_spotify

        if "courant" not in verrous_spotify or not code:
            return HTMLResponse("<p>Connexion Spotify invalide.</p>", 400)
        verificateur, client_id = verrous_spotify.pop("courant")
        ctx = Contexte(config=jarvis.config, coffre=jarvis.coffre, outil=ControleMedia())
        await echanger_code_spotify(ctx, code, verificateur, client_id)
        return HTMLResponse("<p>Spotify est branché à Jarvis. Vous pouvez fermer cette page.</p>")

    # --- WebSocket --------------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        try:
            premier = json.loads(await asyncio.wait_for(websocket.receive_text(), 10))
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return
        a = jarvis.appareils.authentifier(premier.get("jeton"))
        if not a:
            await websocket.close(code=4401)
            return
        websocket.state.appareil = a["id"]
        clients.add(websocket)
        connexion = await jarvis.multi.ouvrir(a, websocket) if getattr(jarvis, "multi", None) else None
        await websocket.send_text(json.dumps({"type": "bienvenue", "donnees": {"appareil": a, "pret": jarvis.metriques.pret}},
                                             ensure_ascii=False))
        try:
            while True:
                msg = json.loads(await websocket.receive_text())
                jarvis.appareils.authentifier(premier.get("jeton"))  # présence (MULTI-02)
                if msg.get("type") == "texte" and msg.get("texte"):
                    asyncio.create_task(_repondre_ws(websocket, msg["texte"], a, msg.get("conversation", "principale")))
                elif msg.get("type") == "confirmer":
                    demande = jarvis.confirmateur.demandes.get(int(msg["id"]))
                    biometrie_requise = bool(msg.get("oui")) and a.get("type") == "android" and not msg.get("biometrie")
                    if demande is not None and demande.peut_confirmer(a["id"]) and not biometrie_requise:
                        jarvis.confirmateur.repondre(int(msg["id"]), bool(msg.get("oui")))
                elif msg.get("type") == "arret":
                    jarvis.orchestrateur.arreter_tout()
                elif connexion is not None and msg.get("type") == "outils":
                    noms = jarvis.multi.enregistrer_outils(connexion, msg.get("outils") or [])
                    await websocket.send_text(json.dumps({"type": "outils_enregistres", "donnees": {"noms": noms}}))
                elif connexion is not None and msg.get("type") == "resultat":
                    jarvis.multi.resultat_distant(msg.get("donnees") or {})
                elif connexion is not None and msg.get("type") == "lu":
                    jarvis.multi.marquer_lu(str(msg.get("id", "")))
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(websocket)
            if connexion is not None:
                jarvis.multi.fermer(connexion)

    async def _repondre_ws(websocket: WebSocket, texte: str, a: dict, conversation: str) -> None:
        debut = time.perf_counter()
        premier = None
        try:
            async for morceau in jarvis.orchestrateur.repondre(texte, canal="texte", conversation=conversation,
                                                               origine=f"texte:{a['id']}"):
                premier = premier or time.perf_counter()
                await websocket.send_text(json.dumps({"type": "morceau", "donnees": {"texte": morceau}},
                                                     ensure_ascii=False))
            await websocket.send_text(json.dumps({"type": "fin", "donnees": {}}))
        except Exception:  # noqa: BLE001
            log.exception("Réponse WebSocket interrompue")
        jarvis.metriques.ajouter(canal="texte", texte=texte,
                                 premier_texte_ms=round(1000 * ((premier or time.perf_counter()) - debut)),
                                 total_ms=round(1000 * (time.perf_counter() - debut)))

    # --- Interface web (PWA) ----------------------------------------------------------------

    if DOSSIER_WEB.exists():
        app.mount("/assets", StaticFiles(directory=DOSSIER_WEB / "assets"), name="assets")

        @app.get("/{chemin:path}")
        async def page(chemin: str):
            fichier = DOSSIER_WEB / chemin
            if chemin and fichier.is_file() and DOSSIER_WEB in fichier.resolve().parents:
                return FileResponse(fichier)
            return FileResponse(DOSSIER_WEB / "index.html")
    else:
        @app.get("/")
        async def page_absente():
            return JSONResponse({"erreur": "Interface non construite : cd web && npm install && npm run build"})

    @app.middleware("http")
    async def entetes_securite(request: Request, suite):
        reponse: Response = await suite(request)
        reponse.headers["X-Content-Type-Options"] = "nosniff"
        reponse.headers["Referrer-Policy"] = "no-referrer"
        reponse.headers["X-Frame-Options"] = "DENY"
        return reponse

    return app


async def servir(jarvis) -> None:
    import uvicorn

    config = uvicorn.Config(creer_app(jarvis), host="127.0.0.1", port=jarvis.config.serveur.port,
                            log_level="warning", ws_ping_interval=20)
    await uvicorn.Server(config).serve()
