"""Budget de contexte : la requête tient toujours dans l'emplacement llama-server.

Mesuré le 14/10 sur le poste de dev : consignes + 69 schémas d'outils ≈ 7 950 tokens. Avec
8 192 tokens par emplacement, une seule réponse longue saturait le contexte et toutes les
requêtes suivantes échouaient (HTTP 400). On retire donc l'historique le plus ancien tant que
la requête dépasse, et le mode jeu (CPU, petit contexte) n'envoie que les outils utiles en partie.
Le préfixe fixe (consignes + outils) ne change pas d'une requête à l'autre : il reste en cache.
"""

from __future__ import annotations

import json
import re

# Étalonné le 14/10 avec llama-server (usage.prompt_tokens, Qwen3.5) : 69 outils = 24 063 caractères
# = 6 992 tokens (3,44 car./token, enrobage du gabarit compris) ; consignes = 3,6 car./token. On
# compte 3,2 pour garder ≈ 8 % de marge (Gemma et Ministral tokenisent un peu différemment).
CARACTERES_PAR_TOKEN = 3.2
SURCOUT_MESSAGE = 8
SURCOUT_OUTILS = 1.0

# Mode jeu : outils utiles en pleine partie (le reste attend la fin de la partie)
OUTILS_JEU = frozenset({
    "date_et_heure", "regler_volume", "controle_media", "jouer_musique", "morceau_en_cours", "sortie_audio",
    "creer_minuteur", "creer_rappel", "creer_rappel_contextuel", "lister_rappels", "annuler_rappel", "memoriser",
    "rechercher_memoire", "statistiques_jeu", "coach_en_direct", "debrief_partie", "regler_proactivite", "meteo",
    "envoyer_message_discord", "lire_discord", "etat_pc", "processus_gourmands",
})

# Repli si le contexte configuré est trop petit pour tous les outils (≈ 7 000 tokens pour 69 outils)
OUTILS_ESSENTIELS = OUTILS_JEU | frozenset({
    "lancer_application", "fermer_application", "gerer_fenetre", "chercher_fichiers", "lire_fichier",
    "ouvrir_fichier", "creer_dossier", "rechercher_web", "lire_page_web", "agenda", "creer_evenement",
    "lire_mails", "envoyer_mail", "lancer_routine", "analyser_ecran", "lancer_tache_de_fond",
})
MARGE_MINIMALE = 2048  # place minimale pour l'historique récent et la réponse


def tokens(objet) -> int:
    texte = objet if isinstance(objet, str) else json.dumps(objet, ensure_ascii=False)
    return int(len(texte) / CARACTERES_PAR_TOKEN) + 1


def tokens_messages(messages: list[dict]) -> int:
    return sum(tokens(m.get("content") or "") + tokens(m.get("tool_calls") or "") + SURCOUT_MESSAGE
               for m in messages)


def tokens_outils(schemas: list[dict] | None) -> int:
    return int(tokens(schemas) * SURCOUT_OUTILS) if schemas else 0


def ajuster(messages: list[dict], schemas: list[dict] | None, capacite: int, reserve: int,
            debut_tour: int) -> int:
    """Retire (en place) l'historique le plus ancien, entre les consignes et `debut_tour`, tant que
    la requête plus la réponse attendue (`reserve`) dépasse `capacite`. Renvoie le nombre de
    messages retirés. On coupe toujours avant un message « user » pour ne pas laisser un résultat
    d'outil orphelin en tête d'historique."""
    fixe = tokens_outils(schemas)
    retires = 0
    while debut_tour - retires > 1 and fixe + tokens_messages(messages) + reserve > capacite:
        fin = 2
        while fin < debut_tour - retires and messages[fin].get("role") != "user":
            fin += 1
        retires += fin - 1
        del messages[1:fin]
    return retires


def raccourcir_resultats(messages: list[dict], debut_tour: int, garder: int = 1500) -> None:
    """Dernier recours dans un long tour : les résultats d'outils déjà lus (tous sauf le dernier)
    sont raccourcis ; le modèle en a déjà tiré ce qu'il fallait."""
    outils = [i for i in range(debut_tour, len(messages)) if messages[i].get("role") == "tool"]
    for i in outils[:-1]:
        contenu = messages[i].get("content") or ""
        if len(contenu) > garder:
            messages[i] = {**messages[i], "content": contenu[:garder] + " […]"}


def place_restante(messages: list[dict], schemas: list[dict] | None, capacite: int) -> int:
    return capacite - tokens_outils(schemas) - tokens_messages(messages)


def tronquer_repetition(texte: str, fois: int = 3) -> str | None:
    """Si le modèle répète en boucle la même phrase (≥ `fois`), renvoie le texte coupé après la
    première occurrence ; sinon None."""
    phrases = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", texte) if len(p.strip()) >= 8]
    if len(phrases) < fois:
        return None
    derniere = phrases[-1] if texte.rstrip().endswith((".", "!", "?", "…")) else (phrases[-2] if len(phrases) > 1 else "")
    if not derniere or sum(p == derniere for p in phrases) < fois:
        return None
    return texte[:texte.find(derniere) + len(derniere)]
