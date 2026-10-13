"""OUT-COM : mail (IMAP / SMTP), agenda (CalDAV ou adresse iCal privée), Discord (bot).

- Tout ce qui est lu (mails, évènements, messages) est une donnée (SEC-02) : jamais une consigne.
- Tout envoi (mail, message, évènement créé) est irréversible ou sortant : toujours confirmé,
  avec le contenu complet sous les yeux de Mathieu (SEC-01).
- Les identifiants viennent du coffre (SEC-05) et ne sont jamais montrés au modèle.
- Chaque connexion ne peut joindre que l'hôte configuré (garde réseau, SEC-04).
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
import re
import smtplib
import ssl
import uuid
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlparse

from jarvis.outils.base import Contexte, Niveau, Outil, Resultat
from jarvis.securite.reseau import GARDE

# --- Mail -----------------------------------------------------------------------------------


def _config(ctx: Contexte):
    return ctx.config.integrations


def _secret(ctx: Contexte, nom: str) -> str:
    valeur = ctx.coffre.lire(nom) if ctx.coffre else None
    if not valeur:
        raise RuntimeError(f"secret « {nom} » absent : python -m jarvis secrets definir {nom}")
    return valeur


def _entete(valeur: str | None) -> str:
    return str(make_header(decode_header(valeur or ""))) if valeur else ""


def texte_du_mail(message: email.message.Message, limite: int = 3000) -> str:
    corps = message.get_body(preferencelist=("plain", "html")) if hasattr(message, "get_body") else None
    if corps is None:
        return ""
    contenu = corps.get_content()
    if corps.get_content_type() == "text/html":
        from bs4 import BeautifulSoup

        contenu = BeautifulSoup(contenu, "html.parser").get_text(" ", strip=True)
    contenu = re.sub(r"\n\s*\n+", "\n\n", contenu)
    contenu = re.split(r"\n(Le .{5,80} a écrit|On .{5,80} wrote)", contenu)[0]  # sans l'historique cité
    return contenu.strip()[:limite]


class BoiteMail:
    """Connexion IMAP courte (ouverte le temps de la requête), limitée à l'hôte configuré."""

    def __init__(self, ctx: Contexte, outil: str):
        c = _config(ctx)
        if not c.imap_hote or not c.imap_utilisateur:
            raise RuntimeError("mail non configuré ([integrations] imap_hote et imap_utilisateur dans jarvis.toml)")
        self.hote, self.utilisateur = c.imap_hote, c.imap_utilisateur
        self.mot_de_passe = _secret(ctx, "imap_mot_de_passe")
        self.outil = outil

    def __enter__(self) -> imaplib.IMAP4_SSL:
        self._garde = GARDE.pour_outil(self.outil, (self.hote,))
        self._garde.__enter__()
        self.cnx = imaplib.IMAP4_SSL(self.hote, ssl_context=ssl.create_default_context(), timeout=20)
        self.cnx.login(self.utilisateur, self.mot_de_passe)
        return self.cnx

    def __exit__(self, *exc):
        try:
            self.cnx.logout()
        finally:
            self._garde.__exit__(*exc)


def lister_mails(ctx: Contexte, outil: str, n: int, non_lus: bool, recherche: str, dossier: str) -> list[dict]:
    with BoiteMail(ctx, outil) as imap:
        imap.select(f'"{dossier}"', readonly=True)  # lecture seule : ne marque pas comme lu
        criteres = ["UNSEEN"] if non_lus else ["ALL"]
        if recherche:
            criteres = [*criteres, "TEXT", f'"{recherche}"']
        _, donnees = imap.uid("SEARCH", "CHARSET", "UTF-8", *criteres) if recherche else imap.uid("SEARCH", *criteres)
        uids = (donnees[0] or b"").split()[-n:]
        mails = []
        for uid in reversed(uids):
            _, brut = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            message = email.message_from_bytes(brut[0][1], policy=email.policy.default)
            nom, adresse = parseaddr(_entete(message["From"]))
            mails.append({"uid": uid.decode(), "de": nom or adresse, "adresse": adresse,
                          "sujet": _entete(message["Subject"]), "date": message["Date"],
                          "extrait": texte_du_mail(message, 600)})
        return mails


def lire_un_mail(ctx: Contexte, outil: str, uid: str, dossier: str) -> dict:
    with BoiteMail(ctx, outil) as imap:
        imap.select(f'"{dossier}"', readonly=True)
        _, brut = imap.uid("FETCH", uid.encode(), "(BODY.PEEK[])")
        if not brut or brut[0] is None:
            raise RuntimeError(f"mail {uid} introuvable")
        message = email.message_from_bytes(brut[0][1], policy=email.policy.default)
        return {"uid": uid, "de": _entete(message["From"]), "sujet": _entete(message["Subject"]),
                "date": message["Date"], "message_id": message["Message-ID"], "texte": texte_du_mail(message)}


class LireMails(Outil):
    nom = "lire_mails"
    description = "Liste les derniers mails (non lus par défaut), avec expéditeur, sujet et extrait. Ne les marque pas comme lus."
    parametres = {"type": "object", "properties": {
        "nombre": {"type": "integer", "description": "10 par défaut."},
        "non_lus": {"type": "boolean", "description": "Seulement les non lus (vrai par défaut)."},
        "recherche": {"type": "string", "description": "Mots à chercher (expéditeur, sujet, contenu)."},
        "dossier": {"type": "string", "description": "INBOX par défaut."}}}
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, nombre: int = 10, non_lus: bool = True, recherche: str = "",
                       dossier: str = "INBOX") -> Resultat:
        mails = await asyncio.to_thread(lister_mails, ctx, self.nom, min(nombre, 30), non_lus, recherche, dossier)
        if not mails:
            return Resultat(True, "Aucun mail correspondant.", donnees=[])
        importants = {a.lower() for a in _config(ctx).expediteurs_importants}
        lignes = [f"[uid {m['uid']}] {'★ ' if m['adresse'].lower() in importants else ''}{m['de']} — {m['sujet']} "
                  f"({m['date']}) : {m['extrait'][:300]}" for m in mails]
        return Resultat(True, "\n".join(lignes), donnees=mails, contenu_externe=True)


class LireMail(Outil):
    nom = "lire_mail"
    description = "Lit un mail complet (par son uid, obtenu avec lire_mails) pour le résumer ou y répondre."
    parametres = {"type": "object", "properties": {"uid": {"type": "string"}, "dossier": {"type": "string"}},
                  "required": ["uid"]}
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, uid: str, dossier: str = "INBOX") -> Resultat:
        m = await asyncio.to_thread(lire_un_mail, ctx, self.nom, str(uid), dossier)
        return Resultat(True, f"De : {m['de']}\nSujet : {m['sujet']}\nDate : {m['date']}\n\n{m['texte']}", donnees=m,
                        contenu_externe=True)


def envoyer(ctx: Contexte, outil: str, destinataire: str, sujet: str, corps: str, en_reponse_a: str | None = None) -> None:
    c = _config(ctx)
    if not c.smtp_hote:
        raise RuntimeError("envoi non configuré ([integrations] smtp_hote)")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = c.imap_utilisateur, destinataire, sujet
    if en_reponse_a:
        message["In-Reply-To"] = message["References"] = en_reponse_a
    message.set_content(corps)
    mot_de_passe = _secret(ctx, "imap_mot_de_passe")
    with GARDE.pour_outil(outil, (c.smtp_hote,)):
        if c.smtp_port == 465:
            with smtplib.SMTP_SSL(c.smtp_hote, 465, context=ssl.create_default_context(), timeout=20) as smtp:
                smtp.login(c.imap_utilisateur, mot_de_passe)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(c.smtp_hote, c.smtp_port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(c.imap_utilisateur, mot_de_passe)
                smtp.send_message(message)


class EnvoyerMail(Outil):
    nom = "envoyer_mail"
    description = ("Envoie un mail. Rédige un texte complet et soigné. Soumis à la confirmation de Mathieu, qui voit "
                   "le message en entier.")
    parametres = {"type": "object", "properties": {
        "destinataire": {"type": "string", "description": "Adresse mail."},
        "sujet": {"type": "string"}, "corps": {"type": "string"},
        "en_reponse_a_uid": {"type": "string", "description": "uid du mail auquel on répond (facultatif)."}},
        "required": ["destinataire", "sujet", "corps"]}
    niveau = Niveau.IRREVERSIBLE

    def decrire(self, args):
        return (f"envoyer un mail à {args.get('destinataire')}, sujet « {args.get('sujet')} » :\n"
                f"{args.get('corps', '')}")

    async def executer(self, ctx: Contexte, destinataire: str, sujet: str, corps: str,
                       en_reponse_a_uid: str = "") -> Resultat:
        if "@" not in parseaddr(destinataire)[1]:
            return Resultat.echec(f"Adresse invalide : {destinataire}. Demande l'adresse exacte à Mathieu.")
        reference = None
        if en_reponse_a_uid:
            reference = (await asyncio.to_thread(lire_un_mail, ctx, self.nom, en_reponse_a_uid, "INBOX"))["message_id"]
        await asyncio.to_thread(envoyer, ctx, self.nom, destinataire, sujet, corps, reference)
        return Resultat(True, f"Mail envoyé à {destinataire}.")


# --- Agenda ---------------------------------------------------------------------------------


def evenements_ics(contenu: bytes | str, debut: datetime, fin: datetime) -> list[dict]:
    """Évènements d'un calendrier iCal compris entre deux dates (récurrences simples développées)."""
    from icalendar import Calendar

    cal = Calendar.from_ical(contenu)
    resultat = []
    for ev in cal.walk("VEVENT"):
        dt = ev.get("dtstart")
        if dt is None:
            continue
        d = dt.dt
        journee = isinstance(d, date) and not isinstance(d, datetime)
        d = datetime.combine(d, datetime.min.time()) if journee else d.replace(tzinfo=None) if d.tzinfo is None else \
            d.astimezone().replace(tzinfo=None)
        dfin = ev.get("dtend")
        f = dfin.dt if dfin else d + timedelta(hours=1)
        if isinstance(f, date) and not isinstance(f, datetime):
            f = datetime.combine(f, datetime.min.time())
        elif f.tzinfo is not None:
            f = f.astimezone().replace(tzinfo=None)
        duree = f - d
        occurrences = [d]
        regle = ev.get("rrule")
        if regle:
            freq = (regle.get("FREQ") or [""])[0]
            pas = {"DAILY": timedelta(days=1), "WEEKLY": timedelta(weeks=1)}.get(freq)
            if pas:
                x = d
                while x < fin and len(occurrences) < 500:
                    x += pas
                    occurrences.append(x)
        for o in occurrences:
            if o < fin and o + duree > debut:
                resultat.append({"titre": str(ev.get("summary", "(sans titre)")), "debut": o, "fin": o + duree,
                                 "journee": journee, "lieu": str(ev.get("location", "") or "")})
    return sorted(resultat, key=lambda e: e["debut"])


class Agenda(Outil):
    nom = "agenda"
    description = "Donne les évènements de l'agenda de Mathieu pour un jour ou une période (aujourd'hui par défaut)."
    parametres = {"type": "object", "properties": {
        "debut": {"type": "string", "description": "Date AAAA-MM-JJ (aujourd'hui par défaut)."},
        "jours": {"type": "integer", "description": "Nombre de jours (1 par défaut)."}}}
    hotes = ("*",)  # l'hôte réel est vérifié : celui de caldav_url ou ics_url uniquement
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, debut: str = "", jours: int = 1) -> Resultat:
        c = _config(ctx)
        source = c.caldav_url or c.ics_url
        if not source:
            return Resultat.echec("Agenda non configuré ([integrations] caldav_url ou ics_url).")
        d = datetime.fromisoformat(debut) if debut else datetime.combine(date.today(), datetime.min.time())
        f = d + timedelta(days=max(1, min(jours, 31)))
        if c.caldav_url:
            contenu = await requete_caldav(ctx, d, f)
        else:
            url = c.ics_url.replace("webcal://", "https://")
            r = await ctx.http("GET", url, hotes=(urlparse(url).hostname or "",))
            r.raise_for_status()
            contenu = r.content
        evenements = await asyncio.to_thread(evenements_ics, contenu, d, f)
        if not evenements:
            return Resultat(True, "Rien dans l'agenda sur cette période.", donnees=[])
        lignes = [f"{e['debut']:%a %d/%m} {'(journée)' if e['journee'] else e['debut'].strftime('%H:%M') + '-' + e['fin'].strftime('%H:%M')}"
                  f" : {e['titre']}{' — ' + e['lieu'] if e['lieu'] else ''}" for e in evenements]
        return Resultat(True, "\n".join(lignes), donnees=[{**e, "debut": e["debut"].isoformat(),
                                                           "fin": e["fin"].isoformat()} for e in evenements],
                        contenu_externe=True)


async def requete_caldav(ctx: Contexte, debut: datetime, fin: datetime) -> bytes:
    c = _config(ctx)
    corps = f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-data/></d:prop>
  <c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
    <c:time-range start="{debut:%Y%m%dT%H%M%S}Z" end="{fin:%Y%m%dT%H%M%S}Z"/>
  </c:comp-filter></c:comp-filter></c:filter>
</c:calendar-query>"""
    r = await ctx.http("REPORT", c.caldav_url, hotes=(urlparse(c.caldav_url).hostname or "",), content=corps.encode(), headers={"Depth": "1", "Content-Type": "application/xml"},
                       auth=(c.caldav_utilisateur or c.imap_utilisateur, _secret(ctx, "caldav_mot_de_passe")))
    r.raise_for_status()
    blocs = re.findall(r"BEGIN:VCALENDAR.*?END:VCALENDAR", r.text, flags=re.S)
    evenements = "".join(re.findall(r"BEGIN:VEVENT.*?END:VEVENT\r?\n?", "".join(blocs), flags=re.S))
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{evenements}END:VCALENDAR\r\n".encode()


class CreerEvenement(Outil):
    nom = "creer_evenement"
    description = "Ajoute un évènement à l'agenda (CalDAV). Soumis à la confirmation de Mathieu."
    parametres = {"type": "object", "properties": {
        "titre": {"type": "string"}, "debut": {"type": "string", "description": "ISO 8601"},
        "fin": {"type": "string", "description": "ISO 8601 (1 h après le début par défaut)"},
        "lieu": {"type": "string"}}, "required": ["titre", "debut"]}
    niveau = Niveau.IRREVERSIBLE
    hotes = ("*",)

    def decrire(self, args):
        return f"ajouter à l'agenda « {args.get('titre')} » le {args.get('debut')}"

    async def executer(self, ctx: Contexte, titre: str, debut: str, fin: str = "", lieu: str = "") -> Resultat:
        from icalendar import Calendar, Event

        c = _config(ctx)
        if not c.caldav_url:
            return Resultat.echec("La création d'évènements demande un agenda CalDAV ([integrations] caldav_url).")
        d = datetime.fromisoformat(debut)
        f = datetime.fromisoformat(fin) if fin else d + timedelta(hours=1)
        cal, ev = Calendar(), Event()
        cal.add("prodid", "-//Jarvis//FR")
        cal.add("version", "2.0")
        ident = f"{uuid.uuid4()}@jarvis"
        ev.add("uid", ident)
        ev.add("summary", titre)
        ev.add("dtstart", d)
        ev.add("dtend", f)
        ev.add("dtstamp", datetime.now())
        if lieu:
            ev.add("location", lieu)
        cal.add_component(ev)
        r = await ctx.http("PUT", c.caldav_url.rstrip("/") + f"/{ident}.ics", hotes=(urlparse(c.caldav_url).hostname or "",),
                           content=cal.to_ical(),
                           headers={"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
                           auth=(c.caldav_utilisateur or c.imap_utilisateur, _secret(ctx, "caldav_mot_de_passe")))
        if r.status_code not in (200, 201, 204):
            return Resultat.echec(f"Le serveur d'agenda a répondu {r.status_code}.")
        return Resultat(True, f"Évènement « {titre} » ajouté le {d:%d/%m à %H:%M}.")


# --- Discord --------------------------------------------------------------------------------

API_DISCORD = "https://discord.com/api/v10"


async def discord(ctx: Contexte, methode: str, chemin: str, **kwargs):
    r = await ctx.http(methode, API_DISCORD + chemin, headers={"Authorization": f"Bot {_secret(ctx, 'discord_jeton_bot')}"},
                       **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"Discord {r.status_code} : {r.text[:200]}")
    return r.json() if r.content else {}


def _salon(ctx: Contexte, salon: str) -> str:
    salons = {k.lower(): v for k, v in _config(ctx).discord_salons.items()}
    if salon.isdigit():
        return salon
    if salon.lower().lstrip("#") in salons:
        return salons[salon.lower().lstrip("#")]
    raise RuntimeError(f"salon inconnu : {salon} (connus : {', '.join(salons) or 'aucun'})")


class LireDiscord(Outil):
    nom = "lire_discord"
    description = "Lit les derniers messages d'un salon Discord configuré, pour les résumer."
    parametres = {"type": "object", "properties": {"salon": {"type": "string"}, "nombre": {"type": "integer"}},
                  "required": ["salon"]}
    hotes = ("discord.com",)
    lit_contenu_externe = True

    async def executer(self, ctx: Contexte, salon: str, nombre: int = 30) -> Resultat:
        messages = await discord(ctx, "GET", f"/channels/{_salon(ctx, salon)}/messages",
                                 params={"limit": max(1, min(nombre, 100))})
        if not messages:
            return Resultat(True, "Aucun message.")
        lignes = [f"{m['timestamp'][:16].replace('T', ' ')} {m['author'].get('global_name') or m['author']['username']} : "
                  f"{m['content'][:400]}" for m in reversed(messages)]
        return Resultat(True, "\n".join(lignes), contenu_externe=True)


class EnvoyerDiscord(Outil):
    nom = "envoyer_message_discord"
    description = ("Poste un message dans un salon Discord configuré, ou en message privé à un contact connu. "
                   "Soumis à la confirmation de Mathieu.")
    parametres = {"type": "object", "properties": {
        "destinataire": {"type": "string", "description": "Nom de salon (ex. general) ou de contact (ex. Théo)."},
        "message": {"type": "string"}}, "required": ["destinataire", "message"]}
    niveau = Niveau.IRREVERSIBLE
    hotes = ("discord.com",)

    def decrire(self, args):
        return f"envoyer sur Discord à {args.get('destinataire')} : « {args.get('message')} »"

    async def executer(self, ctx: Contexte, destinataire: str, message: str) -> Resultat:
        contacts = {k.lower(): v for k, v in _config(ctx).discord_contacts.items()}
        cle = destinataire.lower().lstrip("@#")
        if cle in contacts:
            canal = (await discord(ctx, "POST", "/users/@me/channels", json={"recipient_id": contacts[cle]}))["id"]
        else:
            canal = _salon(ctx, destinataire)
        await discord(ctx, "POST", f"/channels/{canal}/messages",
                      json={"content": message[:2000], "allowed_mentions": {"parse": []}})
        return Resultat(True, f"Message envoyé à {destinataire} sur Discord.")


OUTILS = [LireMails, LireMail, EnvoyerMail, Agenda, CreerEvenement, LireDiscord, EnvoyerDiscord]
