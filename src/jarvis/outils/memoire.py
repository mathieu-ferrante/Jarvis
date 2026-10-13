"""Outils de mémoire (MEM-01 à 04) : retenir, retrouver, dire ce qu'on sait, corriger, oublier."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat
from jarvis.outils.fichiers import EXTENSIONS_TEXTE, extraire_texte, resoudre


def _memoire(ctx: Contexte):
    if ctx.memoire is None:
        raise RuntimeError("mémoire indisponible")
    return ctx.memoire


class Memoriser(Outil):
    nom = "memoriser"
    description = ("Retient durablement un fait sur Mathieu (préférence, projet, habitude, personne), "
                   "formulé à la troisième personne : « Mathieu préfère le thé le matin ».")
    parametres = {"type": "object", "properties": {
        "fait": {"type": "string"},
        "categorie": {"type": "string", "enum": ["preference", "projet", "habitude", "personne", "general"]}},
        "required": ["fait"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"retenir : {args.get('fait')}"

    async def executer(self, ctx: Contexte, fait: str, categorie: str = "general") -> Resultat:
        source = f"dit par Mathieu ({ctx.origine})"
        r = await asyncio.to_thread(_memoire(ctx).memoriser, fait, source, categorie)
        verbe = "mis à jour" if r["mis_a_jour"] else "retenu"
        return Resultat(True, f"Souvenir n° {r['id']} {verbe} : {fait}", donnees=r)

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return _memoire(ctx).fait(resultat.donnees["id"]) is not None


class RechercherMemoire(Outil):
    nom = "rechercher_memoire"
    description = "Cherche dans ce que Jarvis sait de Mathieu (souvenirs) ; sert aussi à dire ce que tu sais sur un sujet."
    parametres = {"type": "object", "properties": {"sujet": {"type": "string"}}, "required": ["sujet"]}

    async def executer(self, ctx: Contexte, sujet: str) -> Resultat:
        faits = await asyncio.to_thread(_memoire(ctx).lister, sujet, 10)
        if not faits:
            return Resultat(True, f"Je ne sais rien sur « {sujet} ».", donnees=[])
        return Resultat(True, " ; ".join(f"n° {f['id']} : {f['texte']} (noté le {f['modifie'][:10]}, {f['source']})"
                                         for f in faits), donnees=faits)


class CorrigerSouvenir(Outil):
    nom = "corriger_souvenir"
    description = "Corrige un souvenir existant (par son numéro, obtenu avec rechercher_memoire)."
    parametres = {"type": "object", "properties": {"id": {"type": "integer"}, "texte": {"type": "string"}},
                  "required": ["id", "texte"]}
    niveau = Niveau.REVERSIBLE

    async def executer(self, ctx: Contexte, id: int, texte: str) -> Resultat:  # noqa: A002
        if await asyncio.to_thread(_memoire(ctx).corriger, id, texte):
            return Resultat(True, f"Souvenir n° {id} corrigé : {texte}")
        return Resultat.echec(f"Aucun souvenir n° {id}.")


class Oublier(Outil):
    nom = "oublier"
    description = "Fait oublier définitivement un souvenir (par son numéro, obtenu avec rechercher_memoire)."
    parametres = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    niveau = Niveau.IRREVERSIBLE

    def decrire(self, args):
        return f"oublier définitivement le souvenir n° {args.get('id')}"

    async def executer(self, ctx: Contexte, id: int) -> Resultat:  # noqa: A002
        fait = _memoire(ctx).fait(id)
        if not fait:
            return Resultat.echec(f"Aucun souvenir n° {id}.")
        await asyncio.to_thread(_memoire(ctx).oublier, id)
        return Resultat(True, f"Oublié : {fait['texte']}", donnees={"id": id})

    async def verifier(self, ctx, args, resultat) -> bool | None:
        return _memoire(ctx).fait(resultat.donnees["id"]) is None


class ChercherConversations(Outil):
    nom = "chercher_conversations"
    description = "Cherche dans l'historique des conversations passées avec Jarvis."
    parametres = {"type": "object", "properties": {"requete": {"type": "string"}}, "required": ["requete"]}

    async def executer(self, ctx: Contexte, requete: str) -> Resultat:
        lignes = await asyncio.to_thread(_memoire(ctx).chercher_historique, requete, 8)
        if not lignes:
            return Resultat(True, "Rien trouvé dans l'historique.")
        return Resultat(True, " ; ".join(f"{l['horodatage'][:16]} — Mathieu : {l['demande'][:120]} → "  # noqa: E741
                                         f"Jarvis : {l['reponse'][:160]}" for l in lignes))


def indexer_dossiers(memoire, dossiers: list[str]) -> dict:
    total, fichiers = 0, 0
    for d in dossiers:
        racine = resoudre(d)
        for dossier, sous, noms in os.walk(racine):
            sous[:] = [s for s in sous if not s.startswith((".", "node_modules", "__pycache__"))]
            for n in noms:
                p = Path(dossier) / n
                if p.suffix.lower() not in EXTENSIONS_TEXTE | {".pdf", ".docx", ".odt"}:
                    continue
                try:
                    modifie = p.stat().st_mtime
                    if memoire.date_document(str(p)) == modifie:
                        continue
                    total += memoire.indexer_texte(str(p), extraire_texte(p, 200_000), modifie)
                    fichiers += 1
                except Exception:  # noqa: BLE001, S112 — fichier illisible : on passe
                    continue
    return {"fichiers": fichiers, "morceaux": total}


class IndexerDocuments(Outil):
    nom = "indexer_documents"
    description = "Ajoute un dossier aux documents que Jarvis peut retrouver par le sens (recherche sémantique locale)."
    parametres = {"type": "object", "properties": {"dossier": {"type": "string"}}, "required": ["dossier"]}
    niveau = Niveau.REVERSIBLE

    async def executer(self, ctx: Contexte, dossier: str) -> Resultat:
        if not resoudre(dossier).is_dir():
            return Resultat.echec(f"{dossier} n'est pas un dossier.")
        r = await asyncio.to_thread(indexer_dossiers, _memoire(ctx), [dossier])
        documents = getattr(getattr(ctx.config, "memoire", None), "documents_indexes", None)
        if documents is not None and dossier not in documents:
            documents.append(dossier)
        return Resultat(True, f"{r['fichiers']} fichier(s) indexé(s), {r['morceaux']} passage(s).")


class ChercherDocuments(Outil):
    nom = "chercher_documents"
    description = "Retrouve, par le sens, des passages dans les documents indexés de Mathieu."
    parametres = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, question: str) -> Resultat:
        passages = await asyncio.to_thread(_memoire(ctx).chercher_documents, question, 4)
        if not passages:
            return Resultat(True, "Aucun document indexé ne correspond.")
        return Resultat(True, "\n\n".join(f"[{p['chemin']}]\n{p['texte'][:1200]}" for p in passages),
                        contenu_externe=True)


OUTILS = [Memoriser, RechercherMemoire, CorrigerSouvenir, Oublier, ChercherConversations, IndexerDocuments,
          ChercherDocuments]


class PropositionsSouvenirs(Outil):
    nom = "propositions_souvenirs"
    description = ("Liste ce que Jarvis propose de retenir (souvenirs déduits des conversations, habitudes repérées), "
                   "en attente de l'accord de Mathieu.")

    async def executer(self, ctx: Contexte) -> Resultat:
        props = await asyncio.to_thread(_memoire(ctx).propositions)
        if not props:
            return Resultat(True, "Aucune proposition en attente.")
        return Resultat(True, " ; ".join(f"n° {p['id']} ({p['origine']}) : {p['texte']}" for p in props), donnees=props)


class ValiderSouvenir(Outil):
    nom = "valider_souvenir"
    description = "Accepte (retient) ou refuse une proposition de souvenir, par son numéro."
    parametres = {"type": "object", "properties": {"id": {"type": "integer"}, "accepter": {"type": "boolean"}},
                  "required": ["id", "accepter"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"{'retenir' if args.get('accepter') else 'écarter'} la proposition n° {args.get('id')}"

    async def executer(self, ctx: Contexte, id: int, accepter: bool) -> Resultat:  # noqa: A002
        r = await asyncio.to_thread(_memoire(ctx).decider_proposition, id, accepter)
        if r is None:
            return Resultat.echec(f"Aucune proposition en attente n° {id}.")
        return Resultat(True, "Retenu." if accepter else "D'accord, je ne le retiens pas et je ne le reproposerai pas.")


OUTILS += [PropositionsSouvenirs, ValiderSouvenir]
