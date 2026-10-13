"""Initiative (lot J8) : briefing du matin, suggestions discrètes, rappels contextuels.

- INI-01 : briefing déclenché à la première activité du jour (clavier / souris après une longue
  inactivité), avec agenda, mails importants, rappels, météo et veille si configurés.
- INI-03 / INI-10 : suggestions basées sur la mémoire, au plus quelques-unes par jour, jamais
  en jeu, désactivables (niveau « silencieux » / « discret » / « actif »), toutes journalisées.
- INI-11 : à la fin d'une partie, les rappels retenus pendant le jeu sont redits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime

from jarvis import chemins
from jarvis.outils import windows as win

log = logging.getLogger(__name__)
INACTIVITE_NUIT_S = 4 * 3600
HEURE_MIN_BRIEFING = 5
SUGGESTIONS_PAR_JOUR = {"silencieux": 0, "discret": 2, "actif": 5}

CONSIGNE_BRIEFING = """Prépare le briefing du matin de Mathieu, à l'oral, en 6 phrases au plus, chaleureux et efficace.
Utilise les outils disponibles pour récupérer, s'ils sont configurés : l'agenda du jour, les mails importants
non lus, les rappels du jour, la météo, la dernière session de jeu. N'invente rien : si une source n'est pas
disponible, n'en parle pas. Termine par une question ou une suggestion utile pour la journée."""

CONSIGNE_SUGGESTION = """Tu es Jarvis. Voici ce que tu sais de Mathieu et ses rappels à venir.
Propose AU PLUS une suggestion concrète, utile maintenant, en une phrase (par ex. « tu m'avais demandé de te
rappeler… »). Si rien ne mérite d'interrompre Mathieu, réponds exactement : RIEN"""


class Initiative:
    def __init__(self, jarvis):
        self.jarvis = jarvis
        self.fichier = chemins.dossier_donnees() / "initiative.json"
        self.etat = json.loads(self.fichier.read_text("utf-8")) if self.fichier.exists() else {}
        self._etait_inactif = True
        self._retenues: list[str] = []
        jarvis.bus.abonner(self._sur_evenement)

    def _sauver(self) -> None:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        self.fichier.write_text(json.dumps(self.etat, ensure_ascii=False), "utf-8")

    @property
    def niveau(self) -> str:
        if not self.jarvis.config.initiative.suggestions:
            return "silencieux"
        return self.etat.get("niveau", "discret")

    def _sur_evenement(self, evt) -> None:
        if evt.type == "voix_annonce_retenue":
            self._retenues.append(evt.donnees.get("texte", ""))
        if evt.type == "jeu" and evt.donnees.get("etat") == "inactif" and self._retenues:
            resume = " ; ".join(self._retenues[-5:])
            self._retenues.clear()
            self.jarvis.bus.notifier("Pendant ta partie", resume, categorie="rappel")

    # --- Briefing ---------------------------------------------------------------------------

    def doit_briefer(self, maintenant: datetime, inactivite_s: float) -> bool:
        if not self.jarvis.config.initiative.briefing or self.jarvis.etat_jeu["en_jeu"]:
            return False
        if self.etat.get("dernier_briefing") == maintenant.date().isoformat() or maintenant.hour < HEURE_MIN_BRIEFING:
            return False
        if inactivite_s > INACTIVITE_NUIT_S:
            self._etait_inactif = True
            return False
        premiere_activite = self._etait_inactif and inactivite_s < 60
        return premiere_activite or self.etat.get("dernier_briefing") is None and inactivite_s < 60

    async def briefing(self) -> str:
        self.etat["dernier_briefing"] = date.today().isoformat()
        self._sauver()
        texte = await self.jarvis.orchestrateur.repondre_texte(CONSIGNE_BRIEFING, canal="voix",
                                                               conversation="briefing", origine="initiative")
        self.jarvis.bus.publier("briefing", texte=texte)
        self.jarvis.bus.notifier("Briefing du matin", texte, categorie="briefing")
        return texte

    # --- Suggestions ------------------------------------------------------------------------

    async def suggestion(self) -> str | None:
        quota = SUGGESTIONS_PAR_JOUR.get(self.niveau, 0)
        aujourd_hui = date.today().isoformat()
        compte = self.etat.get("suggestions", {}).get(aujourd_hui, 0)
        if compte >= quota or self.jarvis.etat_jeu["en_jeu"]:
            return None
        faits = [f["texte"] for f in self.jarvis.memoire.lister(None, 30)]
        rappels = [f"{r['texte']} ({r['quand']})" for r in self.jarvis.rappels.lister()[:10]]
        if not faits and not rappels:
            return None
        messages = [{"role": "system", "content": CONSIGNE_SUGGESTION},
                    {"role": "user", "content": f"Maintenant : {datetime.now():%A %d %B %H:%M}\nSouvenirs : "
                                                f"{' | '.join(faits)}\nRappels : {' | '.join(rappels) or 'aucun'}"}]
        r = await self.jarvis.llm.discuter(messages, max_tokens=80)
        texte = r.texte.strip()
        if not texte or texte.upper().startswith("RIEN"):
            return None
        self.etat.setdefault("suggestions", {})[aujourd_hui] = compte + 1
        self._sauver()
        self.jarvis.journal.consigner(outil="suggestion", arguments={}, niveau="lecture", decision="libre",
                                      origine="initiative", ok=True, resultat=texte)
        self.jarvis.bus.notifier("Suggestion", texte, categorie="suggestion")
        return texte

    # --- Boucle -----------------------------------------------------------------------------

    async def boucle(self) -> None:
        derniere_suggestion = datetime.now()
        derniere_sauvegarde = datetime.fromisoformat(self.etat.get("derniere_sauvegarde", "2000-01-01T00:00:00"))
        while True:
            await asyncio.sleep(20)
            try:
                inactivite = await asyncio.to_thread(win.secondes_inactivite)
                maintenant = datetime.now()
                if self.jarvis.metriques.pret and self.doit_briefer(maintenant, inactivite):
                    self._etait_inactif = False
                    await self.briefing()
                elif inactivite < 60:
                    self._etait_inactif = False
                if self.jarvis.metriques.pret and (maintenant - derniere_suggestion).total_seconds() > 2700 \
                        and inactivite < 300:
                    derniere_suggestion = maintenant
                    await self.suggestion()
                await self._sauvegarde_si_due(maintenant, derniere_sauvegarde)
                if self.etat.get("dernieres_habitudes") != maintenant.date().isoformat() and maintenant.hour >= 12:
                    from jarvis.habitudes import proposer_habitudes  # IA-04, une fois par jour

                    self.etat["dernieres_habitudes"] = maintenant.date().isoformat()
                    self._sauver()
                    await asyncio.to_thread(proposer_habitudes, self.jarvis.journal, self.jarvis.memoire, self.jarvis.bus)
                derniere_sauvegarde = datetime.fromisoformat(self.etat.get("derniere_sauvegarde",
                                                                           derniere_sauvegarde.isoformat()))
            except Exception:  # noqa: BLE001 — l'initiative ne doit jamais tomber
                log.exception("Initiative")

    async def _sauvegarde_si_due(self, maintenant: datetime, derniere: datetime) -> None:
        """MEM-05 : sauvegarde chiffrée automatique vers le disque de sauvegarde."""
        m = self.jarvis.config.memoire
        if not m.dossier_sauvegarde or not self.jarvis.coffre:
            return
        if (maintenant - derniere).total_seconds() < m.sauvegarde_heures * 3600:
            return
        from pathlib import Path

        from jarvis.memoire import sauvegarde

        try:
            fichier = await asyncio.to_thread(sauvegarde.sauvegarder, self.jarvis.coffre, Path(m.dossier_sauvegarde))
            self.etat["derniere_sauvegarde"] = maintenant.isoformat(timespec="seconds")
            self._sauver()
            log.info("Sauvegarde chiffrée : %s", fichier)
        except Exception as e:  # noqa: BLE001
            self.jarvis.bus.notifier("Sauvegarde impossible", str(e), categorie="erreur")
