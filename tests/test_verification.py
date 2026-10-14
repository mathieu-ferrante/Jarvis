"""`python -m jarvis verifier` : contrôles et rapport."""

import subprocess
from types import SimpleNamespace

from jarvis import verification as v
from jarvis.config import Config


def test_dependances_manquantes():
    r = v.dependances(trouver=lambda m: None if m in ("numpy", "piper") else object())
    statuts = {c.libelle: c.statut for c in r}
    assert statuts["Dépendances « socle »"] == v.ECHEC and statuts["Dépendances « voix »"] == v.ATTENTION
    assert statuts["Dépendances « app »"] == v.OK and "piper" in r[1].detail


def test_carte_vue_par_llama_server(monkeypatch, tmp_path):
    monkeypatch.setattr("jarvis.llm.serveur.dossier_binaires", lambda b: tmp_path)
    c = Config()

    def sortie(texte):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=texte, stderr="")

    amd = "Available devices:\n  Vulkan0: AMD Radeon RX 6750 XT (12272 MiB, 11800 MiB free)\n"
    assert v.gpu_vulkan(c, executer=sortie(amd)).statut == v.OK
    assert v.gpu_vulkan(c, executer=sortie("Vulkan0: Intel(R) Iris(R) Xe Graphics (16200 MiB)")).statut == v.ATTENTION
    assert v.gpu_vulkan(c, executer=sortie("ggml_vulkan: No devices found")).statut == v.ECHEC


def test_garde_reseau_refuse_un_fournisseur_d_ia():
    assert v.garde_reseau().statut == v.OK


def test_rapport_sans_secret_et_code_de_retour(monkeypatch, tmp_path):
    monkeypatch.setattr("jarvis.chemins.dossier_donnees", lambda: tmp_path)
    monkeypatch.setattr(v, "tout_verifier", lambda gpu=True: [v.Controle(v.OK, "Python", "3.13"),
                                                             v.Controle(v.ECHEC, "Micro", "a | b")])
    assert v.main([]) == 1
    texte = (tmp_path / "rapport_verification.md").read_text("utf-8")
    assert "1 échec(s)" in texte and "a / b" in texte and "❌ | Micro" in texte
    monkeypatch.setattr(v, "tout_verifier", lambda gpu=True: [v.Controle(v.ATTENTION, "Tailscale", "absent")])
    assert v.main(["--sans-gpu"]) == 0


def test_backend_cpu_signale(monkeypatch, tmp_path):
    monkeypatch.setattr("jarvis.llm.serveur.dossier_binaires", lambda b: tmp_path)
    c = Config()
    c.llm.backend = "cpu"
    r = v.gpu_vulkan(c, executer=lambda *a, **k: SimpleNamespace(stdout="", stderr=""))
    assert r.statut == v.ATTENTION
