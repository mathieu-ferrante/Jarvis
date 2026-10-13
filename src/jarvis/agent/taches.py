"""Tâches de fond planifiées (BRN-03, INI-02, IA-02).

Une tâche longue suit : plan explicite (étapes) → exécution étape par étape avec les outils →
nouvelle tentative d'une étape en échec, avec l'erreur sous les yeux du modèle → compte rendu.
L'état est enregistré sur disque : une tâche interrompue (redémarrage du PC) reprend à l'étape
où elle en était. Mathieu est notifié à la fin.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from jarvis import chemins

log = logging.getLogger(__name__)
ETAPES_MAX = 8
ESSAIS_PAR_ETAPE = 2

CONSIGNE_PLAN = """Tu prépares le plan d'une tâche de fond pour Jarvis. Découpe-la en 2 à {n} étapes concrètes, chacune
réalisable avec les outils disponibles (recherche web, lecture de pages, fichiers, mémoire, etc.).
Réponds UNIQUEMENT par un tableau JSON de chaînes, une par étape, sans commentaire.
Tâche : {objectif}"""


@dataclass
class Etape:
    description: str
    etat: str = "a_faire"  # a_faire, en_cours, faite, echec
    resultat: str = ""
    essais: int = 0


@dataclass
class TacheFond:
    id: int
    objectif: str
    debut: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    etat: str = "en_cours"  # en_cours, terminee, echec, annulee
    etapes: list[Etape] = field(default_factory=list)
    resultat: str = ""
    tache: asyncio.Task | None = field(default=None, repr=False)

    def en_dict(self) -> dict:
        # Sans le champ « tache » (objet asyncio, ni copiable ni sérialisable)
        return {"id": self.id, "objectif": self.objectif, "debut": self.debut, "etat": self.etat,
                "etapes": [asdict(e) for e in self.etapes], "resultat": self.resultat}


def lire_plan(texte: str) -> list[str]:
    debut, fin = texte.find("["), texte.rfind("]")
    if debut >= 0 and fin > debut:
        try:
            etapes = json.loads(texte[debut:fin + 1])
            return [str(e).strip() for e in etapes if str(e).strip()][:ETAPES_MAX]
        except json.JSONDecodeError:
            pass
    lignes = [re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", ligne).strip() for ligne in texte.splitlines()]
    return [ligne for ligne in lignes if len(ligne) > 3][:ETAPES_MAX]


class GestionnaireTaches:
    def __init__(self, orchestrateur, fichier: Path | None = None):
        self.orchestrateur = orchestrateur
        self.fichier = fichier or chemins.dossier_donnees() / "taches.json"
        self.taches: dict[int, TacheFond] = {}
        self._ids = itertools.count(1)
        self._charger()

    # --- Persistance (reprise après redémarrage) ----------------------------------------------

    def _charger(self) -> None:
        if not self.fichier.exists():
            return
        try:
            for d in json.loads(self.fichier.read_text("utf-8")):
                t = TacheFond(d["id"], d["objectif"], d["debut"], d["etat"],
                              [Etape(**e) for e in d.get("etapes", [])], d.get("resultat", ""))
                self.taches[t.id] = t
            self._ids = itertools.count(max(self.taches, default=0) + 1)
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("Fichier des tâches illisible, ignoré")

    def _sauver(self) -> None:
        try:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            recentes = sorted(self.taches.values(), key=lambda t: t.id)[-50:]
            self.fichier.write_text(json.dumps([t.en_dict() for t in recentes], ensure_ascii=False, indent=1), "utf-8")
        except OSError:
            log.exception("Tâches non sauvegardées")

    def reprendre(self) -> list[int]:
        """Relance les tâches interrompues par un arrêt de Jarvis."""
        repris = []
        for t in self.taches.values():
            if t.etat == "en_cours" and t.tache is None:
                t.tache = asyncio.create_task(self._executer(t))
                repris.append(t.id)
        return repris

    # --- Exécution ---------------------------------------------------------------------------

    def lancer(self, objectif: str) -> TacheFond:
        t = TacheFond(next(self._ids), objectif)
        self.taches[t.id] = t
        self._sauver()
        t.tache = asyncio.create_task(self._executer(t))
        self.orchestrateur.bus.publier("tache", id=t.id, objectif=objectif, etat="en_cours")
        return t

    async def _planifier(self, t: TacheFond) -> None:
        reponse = await self.orchestrateur.llm.discuter(
            [{"role": "user", "content": CONSIGNE_PLAN.format(n=ETAPES_MAX, objectif=t.objectif)}], max_tokens=500)
        etapes = lire_plan(reponse.texte) or [t.objectif]
        t.etapes = [Etape(e) for e in etapes]
        self._sauver()
        self.orchestrateur.bus.publier("tache", id=t.id, objectif=t.objectif, etat="planifiee",
                                       etapes=[e.description for e in t.etapes])

    async def _executer(self, t: TacheFond) -> None:
        o = self.orchestrateur
        try:
            if not t.etapes:
                await self._planifier(t)
            for i, etape in enumerate(t.etapes):
                if etape.etat == "faite":
                    continue  # reprise : déjà faite avant l'interruption
                acquis = "\n".join(f"- Étape {k + 1} ({e.description}) : {e.resultat[:400]}"
                                   for k, e in enumerate(t.etapes[:i]) if e.etat == "faite")
                while etape.essais < ESSAIS_PAR_ETAPE and etape.etat != "faite":
                    etape.essais += 1
                    etape.etat = "en_cours"
                    self._sauver()
                    erreur = f"\nLa tentative précédente a échoué : {etape.resultat[:300]}. Corrige l'approche." \
                        if etape.essais > 1 else ""
                    consigne = (f"Tâche de fond : {t.objectif}\nÉtape {i + 1}/{len(t.etapes)} : {etape.description}\n"
                                f"Déjà fait :\n{acquis or '- rien'}{erreur}\nRéalise uniquement cette étape avec les "
                                "outils, puis résume factuellement ce que tu as obtenu. Commence ta réponse par "
                                "ÉCHEC si tu n'as pas pu.")
                    texte = await o.repondre_texte(consigne, canal="texte", conversation=f"tache-{t.id}-{i}",
                                                   origine="tache")
                    etape.resultat = texte
                    etape.etat = "echec" if texte.upper().startswith("ÉCHEC") or not texte else "faite"
                self._sauver()
                o.bus.publier("tache", id=t.id, objectif=t.objectif, etat="etape", numero=i + 1, statut=etape.etat)
            bilan = "\n".join(f"{k + 1}. {e.description} — {e.etat} : {e.resultat[:600]}" for k, e in enumerate(t.etapes))
            t.resultat = await o.repondre_texte(
                f"Rédige le compte rendu final, concis et factuel, de la tâche « {t.objectif} » à partir de ce bilan "
                f"d'étapes (dis clairement ce qui a échoué) :\n{bilan}", canal="texte",
                conversation=f"tache-{t.id}-bilan", origine="tache")
            t.etat = "terminee" if any(e.etat == "faite" for e in t.etapes) else "echec"
        except asyncio.CancelledError:
            t.etat, t.resultat = "annulee", "Tâche annulée."
        except Exception as e:  # noqa: BLE001
            log.exception("Tâche %s en échec", t.id)
            t.etat, t.resultat = "echec", f"Échec : {e}"
        self._sauver()
        o.bus.publier("tache", id=t.id, objectif=t.objectif, etat=t.etat, resultat=t.resultat)
        if t.etat != "annulee":
            o.bus.notifier(f"Tâche terminée : {t.objectif[:60]}", t.resultat[:500], categorie="tache")

    def annuler_tout(self) -> None:
        for t in self.taches.values():
            if t.tache and not t.tache.done():
                t.tache.cancel()

    def liste(self) -> list[dict]:
        return [{"id": t.id, "objectif": t.objectif, "debut": t.debut, "etat": t.etat, "resultat": t.resultat[:300],
                 "etapes": [{"description": e.description, "etat": e.etat} for e in t.etapes]}
                for t in self.taches.values()]
