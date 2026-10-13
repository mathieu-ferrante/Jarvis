"""Lot J15 : rappels selon le lieu, l'appareil, la fin de partie ; continuité entre appareils."""

import asyncio

from aides import orchestrateur

from jarvis.contexte_rappels import RappelsContexte, distance_m, lire_position
from jarvis.evenements import Bus, Evenement


def test_distance_et_position():
    assert 880 < distance_m(43.2965, 5.3698, 43.3047, 5.3714) < 960  # ~0,92 km à Marseille
    assert lire_position("Position : 43.297, 5.370 (précision ~100 m).") == (43.297, 5.370)
    assert lire_position("indisponible") is None


def test_rappel_de_lieu(tmp_path):
    bus = Bus()
    r = RappelsContexte(tmp_path / "r.sqlite", bus)
    r.ajouter("Acheter du pain", "lieu", {"lat": 43.2965, "lon": 5.3698, "rayon_m": 150, "nom": "la boulangerie"})
    assert r.verifier_position(43.31, 5.40) == []  # trop loin
    assert len(r.verifier_position(43.2966, 5.3699)) == 1
    assert r.lister("lieu") == []  # une seule fois
    notif = [e for e in bus.historique if e.type == "notification"]
    assert "Acheter du pain" in notif[0].donnees["texte"] and "boulangerie" in notif[0].donnees["texte"]


def test_rappel_fin_de_partie_et_appareil(tmp_path):
    bus = Bus()
    r = RappelsContexte(tmp_path / "r.sqlite", bus)
    r.ajouter("Sortir le chien", "fin_partie", {})
    r.ajouter("Exporter les photos", "appareil", {"appareil": "Mac"}, recurrent=True)
    r.sur_evenement(Evenement("jeu", {"etat": "actif"}))
    assert not bus.historique
    r.sur_evenement(Evenement("jeu", {"etat": "inactif"}))
    r.sur_evenement(Evenement("appareil", {"etat": "connecte", "nom": "MacBook"}))
    textes = [e.donnees["texte"] for e in bus.historique]
    assert any("chien" in t for t in textes) and any("photos" in t for t in textes)
    assert len(r.lister("appareil")) == 1  # récurrent : reste actif


def test_boucle_position_ne_demande_rien_sans_rappel_de_lieu(tmp_path, monkeypatch):
    import jarvis.contexte_rappels as module

    monkeypatch.setattr(module, "INTERVALLE_POSITION_S", 0.01)
    r = RappelsContexte(tmp_path / "r.sqlite")
    appels = []

    async def demander():
        appels.append(1)
        return (0.0, 0.0)

    async def scenario():
        tache = asyncio.create_task(r.boucle_position(demander))
        await asyncio.sleep(0.1)
        tache.cancel()

    asyncio.run(scenario())
    assert appels == []  # TEL-06 : pas de rappel de lieu, pas de position demandée


def test_continuite_entre_appareils(tmp_path):
    """MULTI-03 : une conversation commencée au PC continue sur le téléphone."""
    o = orchestrateur(tmp_path, ["Noté.", "Tu parlais de la Clio."], [])
    asyncio.run(o.repondre_texte("je dois faire réviser la Clio", canal="voix", origine="voix"))
    asyncio.run(o.repondre_texte("de quelle voiture je parlais ?", canal="texte", origine="texte:telephone"))
    deuxieme = o.llm.recus[1]
    assert any("Clio" in str(m.get("content")) for m in deuxieme)
