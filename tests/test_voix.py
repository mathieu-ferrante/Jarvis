import asyncio

import numpy as np
import pytest

from jarvis.voix import moteurs
from jarvis.voix.audio_es import EntreeSimulee, SortieSimulee
from jarvis.voix.boucle import BoucleVocale, ParametresBoucle, retirer_mot_reveil
from jarvis.voix.phrases import DecoupeurPhrases, pour_la_voix


def son(duree_s: float, fort: bool = True) -> np.ndarray:
    t = np.arange(int(16000 * duree_s)) / 16000
    return ((0.3 if fort else 0.0) * np.sin(2 * np.pi * 300 * t)).astype(np.float32)


class CerveauFactice:
    def __init__(self, reponse: str, delai: float = 0.0):
        self.reponse = reponse
        self.delai = delai
        self.questions = []

    async def repondre(self, texte, canal="voix"):
        self.questions.append(texte)
        for mot in self.reponse.split(" "):
            await asyncio.sleep(self.delai)
            yield mot + " "


def boucle(entree, cerveau, textes, sortie=None, **params):
    evenements = []
    b = BoucleVocale(
        entree=entree, sortie=sortie or SortieSimulee(), reveil=moteurs.DetecteurReveilFactice(),
        vad=moteurs.DetecteurParoleEnergie(), stt=moteurs.TranscripteurFactice(textes),
        tts=moteurs.SyntheseFactice(), cerveau=cerveau,
        parametres=ParametresBoucle(**{"ecoute_continue_s": 0.5, **params}),
        sur_evenement=lambda t, d: evenements.append((t, d)),
    )
    return b, evenements


def test_decoupeur_phrases():
    d = DecoupeurPhrases()
    sortie = []
    for morceau in ["Il est quatorze", " heures. Il fera beau", " à Marseille ! Veux-tu", " autre chose"]:
        sortie += d.ajouter(morceau)
    assert sortie == ["Il est quatorze heures.", "Il fera beau à Marseille !"]
    assert d.vider() == ["Veux-tu autre chose"]


def test_decoupeur_ne_coupe_pas_les_decimales():
    d = DecoupeurPhrases()
    assert d.ajouter("La température est de 21.5 degrés aujourd'hui. Fin") == [
        "La température est de 21.5 degrés aujourd'hui."]


def test_pour_la_voix_retire_le_markdown():
    assert pour_la_voix("**Attention** : voir `config` et [la doc](http://x)") == "Attention : voir config et la doc"
    assert pour_la_voix("Batterie à 80%") == "Batterie à 80 pour cent"


def test_retirer_mot_reveil():
    assert retirer_mot_reveil("Jarvis, baisse le son.") == "baisse le son."
    assert retirer_mot_reveil("Hey Jarvis quelle heure est-il") == "quelle heure est-il"
    assert retirer_mot_reveil("Djarvis, lance Spotify") == "lance Spotify"
    assert retirer_mot_reveil("Lance Spotify") == "Lance Spotify"


def test_contient_jarvis():
    for texte in ("Jarvis", "jarvi tu es là", "Djarvis !", "jarvice", "Hé Jarvis"):
        assert moteurs.contient_jarvis(texte), texte
    for texte in ("Jarnac", "j'arrive", "service", "lance Spotify"):
        assert not moteurs.contient_jarvis(texte), texte


def test_echange_complet():
    async def scenario():
        entree = EntreeSimulee([son(0.5, False), son(1.2), son(0.8, False)], silence_final_s=1.5)
        cerveau = CerveauFactice("Il est quatorze heures. Autre chose ?")
        b, evts = boucle(entree, cerveau, ["Jarvis, quelle heure est-il ?"])
        await asyncio.wait_for(b.executer(), 10)
        return b, evts, cerveau

    b, evts, cerveau = asyncio.run(scenario())
    types = [t for t, _ in evts]
    assert "reveil" in types and "transcription" in types and "reponse" in types
    assert cerveau.questions == ["quelle heure est-il ?"]
    assert b.tts.phrases == ["Il est quatorze heures.", "Autre chose ?"]
    assert len(b.sortie.joue) == 2
    assert b.mesures and b.mesures[0].latence_ms is not None


def test_transcription_vide_ne_sollicite_pas_le_cerveau():
    async def scenario():
        entree = EntreeSimulee([son(1.0), son(0.8, False)], silence_final_s=1.0)
        cerveau = CerveauFactice("rien")
        b, _ = boucle(entree, cerveau, [""])
        await asyncio.wait_for(b.executer(), 10)
        return cerveau

    assert asyncio.run(scenario()).questions == []


@pytest.mark.parametrize("mode", ["reveil", "vad"])
def test_interruption_coupe_la_parole(mode):
    async def scenario():
        entree = EntreeSimulee([son(1.0), son(0.6, False)], temps_reel=True, silence_final_s=4.0)
        sortie = SortieSimulee(vitesse=1.0)
        longue = "Voici une très longue réponse qui va durer longtemps. " * 6
        b, evts = boucle(entree, CerveauFactice(longue), ["raconte-moi une histoire", "stop"], sortie=sortie,
                         interruption=mode)

        async def couper_pendant_la_parole():
            while b.etat != "parole":
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.3)
            entree.injecter(son(0.5))

        await asyncio.gather(asyncio.wait_for(b.executer(), 20), couper_pendant_la_parole())
        return b, evts

    b, evts = asyncio.run(scenario())
    assert b.sortie.coupures >= 1
    assert "interruption" in [t for t, _ in evts]


def test_ecoute_continue_sans_mot_de_reveil():
    async def scenario():
        # Après la réponse, une seconde phrase sans réveil (le réveil factice exige 3 trames fortes,
        # la seconde phrase est courte et douce : seule l'écoute continue peut la capter).
        entree = EntreeSimulee([son(1.0), son(0.6, False)], temps_reel=True, silence_final_s=2.5)
        cerveau = CerveauFactice("D'accord, c'est noté.")
        b, _ = boucle(entree, cerveau, ["première", "seconde"], ecoute_continue_s=3.0)

        async def relancer():
            while not b.mesures:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.2)
            entree.injecter(0.05 * son(0.6) / 0.3)  # -35 dBFS : parole pour le VAD, pas pour le réveil

        await asyncio.gather(asyncio.wait_for(b.executer(), 20), relancer())
        return cerveau

    assert asyncio.run(scenario()).questions == ["première", "seconde"]


def test_arret_d_urgence_et_annonce_silencieuse():
    async def scenario():
        entree = EntreeSimulee([son(0.3, False)], silence_final_s=0.5)
        b, evts = boucle(entree, CerveauFactice("x"), [])
        b.silencieux = lambda: True
        assert not b.annoncer("rappel non urgent")
        assert b.annoncer("alerte", urgent=True)
        b.arreter_tout()
        await asyncio.wait_for(b.executer(), 5)
        return evts

    types = [t for t, _ in asyncio.run(scenario())]
    assert "annonce_retenue" in types and "arret" in types
