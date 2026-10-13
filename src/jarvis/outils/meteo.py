"""Météo (Open-Meteo, service public sans clé). La requête ne contient que la ville demandée."""

from __future__ import annotations

from jarvis.outils.base import Contexte, Outil, Resultat

CODES = {0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert", 45: "brouillard",
         48: "brouillard givrant", 51: "bruine légère", 53: "bruine", 55: "bruine forte", 61: "pluie faible",
         63: "pluie", 65: "pluie forte", 71: "neige faible", 73: "neige", 75: "neige forte", 80: "averses",
         81: "averses", 82: "fortes averses", 95: "orages", 96: "orages avec grêle", 99: "orages violents"}


async def previsions(ctx: Contexte, ville: str = "", latitude: float | None = None, longitude: float | None = None,
                     jours: int = 3) -> dict:
    nom = ville
    if latitude is None or (ville and ville.lower() != getattr(ctx.config.initiative, "ville_meteo", "").lower()):
        if ville:
            g = await ctx.http("GET", "https://geocoding-api.open-meteo.com/v1/search",
                               params={"name": ville, "count": 1, "language": "fr"})
            resultats = g.json().get("results") or []
            if not resultats:
                raise ValueError(f"Ville inconnue : {ville}")
            latitude, longitude, nom = resultats[0]["latitude"], resultats[0]["longitude"], resultats[0]["name"]
        else:
            latitude, longitude = ctx.config.initiative.latitude, ctx.config.initiative.longitude
            nom = ctx.config.initiative.ville_meteo
    r = await ctx.http("GET", "https://api.open-meteo.com/v1/forecast", params={
        "latitude": latitude, "longitude": longitude, "timezone": "Europe/Paris", "forecast_days": jours,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    r.raise_for_status()
    return {"ville": nom, **r.json()}


def resumer(donnees: dict, jour: str | None = None) -> str:
    quotidien = donnees["daily"]
    lignes = []
    if not jour and donnees.get("current"):
        c = donnees["current"]
        lignes.append(f"Actuellement à {donnees['ville']} : {c['temperature_2m']:.0f} °C, "
                      f"{CODES.get(c['weather_code'], 'temps variable')}")
    for i, date in enumerate(quotidien["time"]):
        if jour and date != jour:
            continue
        lignes.append(f"{date} : {CODES.get(quotidien['weather_code'][i], 'variable')}, "
                      f"{quotidien['temperature_2m_min'][i]:.0f} à {quotidien['temperature_2m_max'][i]:.0f} °C, "
                      f"pluie {quotidien['precipitation_probability_max'][i] or 0} %")
    return " ; ".join(lignes) or "Pas de prévision pour ce jour."


class Meteo(Outil):
    nom = "meteo"
    description = "Donne la météo (actuelle et prévisions sur 7 jours) d'une ville ; par défaut celle de Mathieu."
    parametres = {"type": "object", "properties": {
        "ville": {"type": "string"},
        "jour": {"type": "string", "description": "Date AAAA-MM-JJ (facultatif)."}}}
    hotes = ("api.open-meteo.com", "geocoding-api.open-meteo.com")

    async def executer(self, ctx: Contexte, ville: str = "", jour: str = "") -> Resultat:
        try:
            donnees = await previsions(ctx, ville, jours=7)
        except ValueError as e:
            return Resultat.echec(str(e))
        return Resultat(True, resumer(donnees, jour or None), donnees=donnees["daily"])


OUTILS = [Meteo]
