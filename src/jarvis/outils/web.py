"""OUT-WEB : recherche, lecture de pages, ouverture de liens, rendu de pages dynamiques (navigateur).

Les requêtes partent vers le moteur de recherche et les sites consultés, jamais vers un
fournisseur d'IA (liste noire dans `securite.reseau`). Le contenu lu est une donnée (SEC-02).
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import urllib.parse
import webbrowser

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat
from jarvis.securite.reseau import GARDE, est_fournisseur_ia

TAILLE_MAX_PAGE = 9000


def url_autorisee(url: str) -> str | None:
    """Refuse les schémas exotiques, les fournisseurs d'IA et les adresses locales/privées (SSRF)."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "seules les adresses http(s) sont lues"
    if est_fournisseur_ia(p.hostname):
        return "adresse d'un fournisseur d'IA : interdite"
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return "adresse locale ou privée : non lue par l'outil web"
    except OSError:
        return None  # résolution impossible ici : la requête échouera proprement
    return None


def extraire_contenu(html: str, url: str = "") -> tuple[str, str]:
    """(titre, texte principal) d'une page HTML."""
    from bs4 import BeautifulSoup

    soupe = BeautifulSoup(html, "html.parser")
    titre = (soupe.title.string or "").strip() if soupe.title else ""
    for balise in soupe(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]):
        balise.decompose()
    racine = soupe.find("article") or soupe.find("main") or soupe.body or soupe
    lignes = []
    for el in racine.find_all(["h1", "h2", "h3", "p", "li", "pre", "td", "blockquote"]):
        texte = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if len(texte) > 2:
            lignes.append(("## " if el.name in ("h1", "h2", "h3") else "") + texte)
    texte = "\n".join(dict.fromkeys(lignes))  # sans doublons, ordre gardé
    if len(texte) < 80:  # page sans structure exploitable : texte brut
        texte = re.sub(r"\s+", " ", racine.get_text(" ", strip=True))
    return titre, texte[:TAILLE_MAX_PAGE]


def analyser_resultats_ddg(html: str, n: int = 6) -> list[dict]:
    from bs4 import BeautifulSoup

    soupe = BeautifulSoup(html, "html.parser")
    resultats = []
    for bloc in soupe.select(".result"):
        lien = bloc.select_one("a.result__a")
        if not lien:
            continue
        href = lien.get("href", "")
        cible = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        if "duckduckgo.com/y.js" in cible:  # publicité
            continue
        extrait = bloc.select_one(".result__snippet")
        resultats.append({"titre": lien.get_text(" ", strip=True), "url": cible,
                          "extrait": extrait.get_text(" ", strip=True) if extrait else ""})
        if len(resultats) >= n:
            break
    return resultats


class RechercherWeb(Outil):
    nom = "rechercher_web"
    description = ("Recherche sur le web (DuckDuckGo) pour une information récente ou que tu ne connais pas. "
                   "Lis ensuite les pages utiles avec lire_page_web, et cite tes sources.")
    parametres = {"type": "object", "properties": {"requete": {"type": "string"}}, "required": ["requete"]}
    hotes = ("html.duckduckgo.com", "duckduckgo.com")
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, requete: str) -> Resultat:
        r = await ctx.http("POST", "https://html.duckduckgo.com/html/", data={"q": requete, "kl": "fr-fr"})
        r.raise_for_status()
        resultats = analyser_resultats_ddg(r.text)
        if not resultats:
            return Resultat(True, "Aucun résultat.", donnees=[])
        texte = "\n".join(f"{i + 1}. {x['titre']} — {x['url']}\n   {x['extrait']}" for i, x in enumerate(resultats))
        return Resultat(True, texte, donnees=resultats, contenu_externe=True)


class LirePageWeb(Outil):
    nom = "lire_page_web"
    description = "Lit le contenu principal d'une page web (article, documentation…) pour le résumer ou répondre."
    parametres = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
    hotes = ("*",)  # tout site public, sauf fournisseurs d'IA et adresses privées
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, url: str) -> Resultat:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        def verifier_url() -> str | None:
            with GARDE.pour_outil(self.nom, self.hotes):  # la résolution DNS est celle de l'outil
                return url_autorisee(url)

        refus = await asyncio.to_thread(verifier_url)
        if refus:
            return Resultat.echec(f"Page non lue : {refus}.")
        r = await ctx.http("GET", url, headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6"})
        if r.status_code in (403, 429) and _playwright_disponible():
            titre, texte = await rendre_page(url)  # certains sites refusent les clients non navigateurs
            return Resultat(True, f"{titre}
{url}

{texte}", contenu_externe=True)
        if r.status_code >= 400:
            return Resultat.echec(f"La page répond {r.status_code}.")
        type_contenu = r.headers.get("content-type", "")
        if "pdf" in type_contenu:
            import io

            from pypdf import PdfReader

            lecteur = PdfReader(io.BytesIO(r.content))
            texte = "\n".join((p.extract_text() or "") for p in lecteur.pages[:15])[:TAILLE_MAX_PAGE]
            titre = url
        elif "html" in type_contenu or not type_contenu:
            titre, texte = await asyncio.to_thread(extraire_contenu, r.text, url)
            if len(texte) < 300 and _playwright_disponible():
                titre, texte = await rendre_page(url)  # page dynamique (JavaScript)
        else:
            texte, titre = r.text[:TAILLE_MAX_PAGE], url
        return Resultat(True, f"{titre}\n{url}\n\n{texte}", contenu_externe=True)


def _playwright_disponible() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


async def rendre_page(url: str) -> tuple[str, str]:
    """Rendu complet par Microsoft Edge déjà installé (aucun navigateur téléchargé)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        navigateur = await p.chromium.launch(channel="msedge", headless=True)
        try:
            page = await navigateur.new_page(locale="fr-FR")
            await page.goto(url, wait_until="networkidle", timeout=20000)
            html = await page.content()
        finally:
            await navigateur.close()
    return extraire_contenu(html, url)


class OuvrirLien(Outil):
    nom = "ouvrir_lien"
    description = "Ouvre une adresse web dans le navigateur de Mathieu."
    parametres = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
    niveau = Niveau.REVERSIBLE

    def decrire(self, args):
        return f"ouvrir {args.get('url')} dans le navigateur"

    async def executer(self, ctx: Contexte, url: str) -> Resultat:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return Resultat.echec("Adresse refusée.")
        webbrowser.open(url)
        return Resultat(True, f"{url} ouvert dans le navigateur.")


OUTILS = [RechercherWeb, LirePageWeb, OuvrirLien]
