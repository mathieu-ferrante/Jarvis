from jarvis.diagnostic import batterie


def cas(**kw):
    base = {"id": "t", "tags": ["simple"], "demande": "x", "attendu": []}
    base.update(kw)
    return base


def test_batterie_bien_formee():
    bat = batterie.charger()
    noms = {o["function"]["name"] for o in bat["outils"]}
    ids = [c["id"] for c in bat["cas"]]
    assert len(ids) == len(set(ids)), "identifiants de cas en double"
    for c in bat["cas"]:
        for att in c.get("attendu", []):
            assert att["outil"] in noms, f"{c['id']} attend un outil inconnu"
        for interdit in c.get("interdits", []):
            assert interdit in noms


def test_appel_correct():
    c = cas(attendu=[{"outil": "regler_volume", "args": {"niveau": {"egal": 30}}}])
    assert batterie.noter(c, [{"outil": "regler_volume", "args": {"niveau": 30}}], "").reussi
    assert batterie.noter(c, [{"outil": "regler_volume", "args": {"niveau": "30"}}], "").reussi
    assert not batterie.noter(c, [{"outil": "regler_volume", "args": {"niveau": 40}}], "").reussi
    assert not batterie.noter(c, [], "C'est fait.").reussi


def test_appel_en_trop_refuse():
    c = cas(attendu=[{"outil": "lancer_application", "args": {"nom": {"contient": "spotify"}}}])
    appels = [{"outil": "lancer_application", "args": {"nom": "Spotify"}},
              {"outil": "fermer_application", "args": {"nom": "Discord"}}]
    v = batterie.noter(c, appels, "")
    assert not v.reussi and "incorrect" in v.motif


def test_accents_et_casse_ignores():
    c = cas(attendu=[{"outil": "envoyer_message", "args": {"destinataire": {"contient_un": ["théo"]}}}])
    assert batterie.noter(c, [{"outil": "envoyer_message", "args": {"destinataire": "THEO"}}], "").reussi


def test_sans_outil_exige_du_francais():
    c = cas(tags=["sans_outil"])
    assert batterie.noter(c, [], "Ça va très bien, merci !").reussi
    assert not batterie.noter(c, [], "I am fine, thank you.").reussi
    assert not batterie.noter(c, [], "我很好").reussi
    assert not batterie.noter(c, [{"outil": "meteo", "args": {"ville": "Paris"}}], "").reussi


def test_reponse_contient():
    c = cas(reponse_contient=["391"])
    assert batterie.noter(c, [], "17 × 23 = 391").reussi
    assert batterie.noter(c, [], "Cela fait 391.").reussi
    assert not batterie.noter(c, [], "Cela fait 400.").reussi


def test_outil_interdit():
    c = cas(interdits=["supprimer_fichier"])
    v = batterie.noter(c, [{"outil": "supprimer_fichier", "args": {"chemin": "x"}}], "")
    assert not v.reussi and "interdit" in v.motif


def test_tolerer_autres_outils():
    c = cas(interdits=["envoyer_message"], tolerer_autres_outils=True)
    assert batterie.noter(c, [{"outil": "lancer_application", "args": {"nom": "Steam"}}], "").reussi


def test_multi_un_appel_suffit_et_parallele_releve():
    c = cas(multi=True, attendu=[
        {"outil": "regler_volume", "args": {"niveau": {"egal": 20}}},
        {"outil": "lancer_application", "args": {"nom": {"contient": "steam"}}},
    ])
    un = batterie.noter(c, [{"outil": "regler_volume", "args": {"niveau": 20}}], "")
    assert un.reussi and un.parallele is False
    deux = batterie.noter(c, [{"outil": "regler_volume", "args": {"niveau": 20}},
                              {"outil": "lancer_application", "args": {"nom": "Steam"}}], "")
    assert deux.reussi and deux.parallele is True


def test_synthese():
    v1 = batterie.Verdict("a", ["simple"], True)
    v2 = batterie.Verdict("b", ["simple", "date"], False, motif="raté")
    s = batterie.synthese([v1, v2])
    assert s["taux"] == 0.5
    assert s["par_tag"]["simple"] == 0.5 and s["par_tag"]["date"] == 0.0
    assert s["echecs"] == [{"id": "b", "motif": "raté"}]
