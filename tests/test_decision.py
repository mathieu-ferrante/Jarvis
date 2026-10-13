from jarvis.diagnostic import decision, rapport


def llm(cle, role="principal", taux=0.9, simple=0.95, phrase=500, gen=40, memoire=8.0, cpu=False):
    return {"modele": cle, "nom": cle, "role": role, "cpu_seul": cpu, "memoire_prevue_go": memoire,
            "bench": {"tg128_tok_s": gen, "pp512_tok_s": 800},
            "latence": {"chaud_premiere_phrase_ms": phrase, "chaud_premier_jeton_ms": phrase / 2,
                        "generation_tok_s": gen},
            "batterie": {"taux": taux, "par_tag": {"simple": simple, "securite": 1.0}, "echecs": []}}


def test_principal_meilleur_taux():
    choix = decision.choisir_llm_principal([llm("a", taux=0.86), llm("b", taux=0.93), llm("c", taux=0.80)])
    assert choix["choix"] == "b" and choix["conforme_nf02"]


def test_principal_egalite_departagee_par_vitesse():
    choix = decision.choisir_llm_principal([llm("lent", taux=0.93, phrase=900), llm("vif", taux=0.91, phrase=400)])
    assert choix["choix"] == "vif"


def test_principal_trop_gros_ou_trop_lent_ecarte():
    mesures = [llm("gros", taux=0.97, memoire=13.0), llm("lent", taux=0.95, gen=8), llm("ok", taux=0.88)]
    assert decision.choisir_llm_principal(mesures)["choix"] == "ok"


def test_principal_aucun_eligible_reste_provisoire():
    choix = decision.choisir_llm_principal([llm("a", taux=0.5), llm("b", taux=0.6)])
    assert choix["choix"] == "b" and choix["provisoire"]


def test_rapide_meme_modele_si_assez_vif():
    mesures = [llm("p", phrase=400), llm("r", role="rapide", phrase=200)]
    assert decision.choisir_llm_rapide(mesures, "p")["choix"] == "p"


def test_rapide_petit_modele_sinon():
    mesures = [llm("p", phrase=900), llm("r1", role="rapide", phrase=300, simple=0.95),
               llm("r2", role="rapide", phrase=200, simple=0.7)]
    assert decision.choisir_llm_rapide(mesures, "p")["choix"] == "r1"


def test_stt_privilegie_micro_et_vitesse():
    mesures = [
        {"modele": "lent", "latence_mediane_ms": 900, "wer_propre": 0.01, "wer_bruit": 0.02, "wer_micro": 0.03},
        {"modele": "precis", "latence_mediane_ms": 450, "wer_propre": 0.05, "wer_bruit": 0.10, "wer_micro": 0.05},
        {"modele": "vif", "latence_mediane_ms": 200, "wer_propre": 0.03, "wer_bruit": 0.05, "wer_micro": 0.06},
    ]
    assert decision.choisir_stt(mesures)["choix"].startswith("vif")


def test_tts_kokoro_si_assez_rapide():
    mesures = [{"voix": "piper-siwis", "moteur": "piper", "premiere_phrase_ms": 80},
               {"voix": "kokoro", "moteur": "kokoro", "premiere_phrase_ms": 250}]
    assert decision.choisir_tts(mesures)["choix"] == "kokoro"
    mesures[1]["premiere_phrase_ms"] = 600
    assert decision.choisir_tts(mesures)["choix"] == "piper-siwis"


def test_budget_latence():
    b = decision.budget_latence(300, 500, 150)
    assert b["estimation_ms"] == decision.FIN_DE_PAROLE_MS + 950 and b["tenu"]
    assert decision.budget_latence(None, 500, 100)["estimation_ms"] is None


def test_decider_et_rapport_sur_donnees_completes(tmp_path):
    resultats = {
        "date": "2026-10-13T12:00", "rapide": False, "erreurs": [],
        "systeme": {"cpu": "Ryzen", "gpus": [{"nom": "RX 6750 XT", "pilote": "x"}]},
        "llm": [llm("a"), llm("b", taux=0.95, phrase=650), llm("r", role="rapide", phrase=200),
                llm("r", role="rapide", cpu=True, gen=12)],
        "stt": [{"modele": "fw-small", "latence_mediane_ms": 300, "wer_propre": 0.05, "wer_bruit": 0.1}],
        "tts": [{"voix": "piper-siwis", "moteur": "piper", "premiere_phrase_ms": 90}],
        "reveil": {"modele": "hey", "seuil": 0.5, "cpu": {"pct_cpu_total": 0.4, "pct_d_un_coeur": 6}},
    }
    resultats["decisions"] = decision.decider(resultats)
    assert resultats["decisions"]["llm_principal"]["choix"] == "b"
    assert resultats["decisions"]["mode_jeu"]["choix"] == "r"
    assert resultats["decisions"]["budget_latence"]["estimation_ms"] is not None
    md = rapport.ecrire_markdown(resultats, tmp_path / "r.md").read_text("utf-8")
    assert "Modèle principal" in md and "fw-small" in md
    js = rapport.ecrire_json({**resultats, "x": float("inf")}, tmp_path / "r.json").read_text("utf-8")
    assert "Infinity" not in js
