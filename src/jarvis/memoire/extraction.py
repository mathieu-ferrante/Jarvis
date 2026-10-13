"""Souvenirs automatiques : après un échange, Jarvis retient les faits durables qu'il a appris.

Chaque souvenir déduit porte la source « déduit de la conversation » : Mathieu peut demander ce
que Jarvis sait, corriger ou faire oublier (MEM-03). Désactivable (`souvenirs_automatiques`).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

CONSIGNE = """Tu extrais des souvenirs durables sur Mathieu à partir d'un échange avec son assistant.
Ne retiens que ce qui restera vrai et utile dans plusieurs semaines : préférences, habitudes, projets en cours,
personnes de son entourage, équipement, objectifs. Ignore les demandes ponctuelles (« baisse le son »),
la météo, les questions de culture générale, et tout ce qui vient d'un contenu lu (mail, page web).
Chaque fait est une phrase autonome à la troisième personne commençant par « Mathieu ».
Réponds UNIQUEMENT par un tableau JSON de chaînes, vide s'il n'y a rien : []"""

_DECLENCHEURS = re.compile(
    r"\b(je (suis|préfère|n'aime|aime|adore|déteste|joue|travaille|bosse|veux|voudrais|vais|habite|fais|"
    r"m'entraîne|commence|prépare|apprends)|mon |ma |mes |j'ai |appelle-moi|souviens-toi|n'oublie pas|"
    r"d'habitude|toujours|jamais|tous les|chaque (jour|soir|matin|semaine))\b", re.I)


def merite_extraction(demande: str) -> bool:
    """Filtre peu coûteux : inutile de solliciter le modèle pour « baisse le son »."""
    return len(demande.split()) >= 4 and bool(_DECLENCHEURS.search(demande))


def lire_faits(texte: str) -> list[str]:
    debut, fin = texte.find("["), texte.rfind("]")
    if debut < 0 or fin <= debut:
        return []
    try:
        faits = json.loads(texte[debut:fin + 1])
    except json.JSONDecodeError:
        return []
    return [f.strip() for f in faits if isinstance(f, str) and f.strip().lower().startswith("mathieu")][:5]


async def extraire_et_retenir(client, memoire, demande: str, reponse: str, bus=None, a_valider: bool = True) -> list[str]:
    if not merite_extraction(demande):
        return []
    messages = [{"role": "system", "content": CONSIGNE},
                {"role": "user", "content": f"Mathieu : {demande}\nAssistant : {reponse}"}]
    try:
        r = await client.discuter(messages, max_tokens=300)
    except Exception:  # noqa: BLE001 — jamais bloquant
        log.exception("Extraction de souvenirs impossible")
        return []
    retenus = []
    for fait in lire_faits(r.texte):
        if a_valider:  # IA-04 : proposé à Mathieu, retenu seulement s'il accepte
            ident = memoire.proposer(fait, "conversation")
            if ident is not None:
                retenus.append(fait)
                if bus:
                    bus.publier("proposition_souvenir", texte=fait, id=ident)
            continue
        resultat = memoire.memoriser(fait, source="déduit de la conversation", categorie="general")
        retenus.append(fait)
        if bus and not resultat["mis_a_jour"]:
            bus.publier("souvenir", texte=fait, id=resultat["id"])
    return retenus
