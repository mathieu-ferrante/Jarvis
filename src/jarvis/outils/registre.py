"""Registre des outils : découverte automatique des modules de `jarvis.outils` et des outils perso."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import sys
from pathlib import Path

from jarvis import chemins
from jarvis.outils.base import Outil

log = logging.getLogger(__name__)
_IGNORES = {"base", "registre"}


class Registre:
    def __init__(self):
        self.outils: dict[str, Outil] = {}
        self.erreurs: list[str] = []

    def ajouter(self, outil: Outil) -> None:
        if not outil.nom or not outil.nom.isidentifier():
            raise ValueError(f"Nom d'outil invalide : {outil.nom!r}")
        if outil.nom in self.outils:
            raise ValueError(f"Outil en double : {outil.nom}")
        if outil.windows_seulement and sys.platform != "win32":
            return
        self.outils[outil.nom] = outil

    def _depuis_module(self, module) -> None:
        for objet in getattr(module, "OUTILS", []):
            self.ajouter(objet() if isinstance(objet, type) else objet)

    def charger_tout(self, dossier_perso: Path | None = None) -> Registre:
        import jarvis.outils as paquet

        for info in pkgutil.iter_modules(paquet.__path__):
            if info.name in _IGNORES or info.name.startswith("_"):
                continue
            try:
                self._depuis_module(importlib.import_module(f"jarvis.outils.{info.name}"))
            except Exception as e:  # noqa: BLE001 — un module cassé ne doit pas tout bloquer
                self.erreurs.append(f"{info.name} : {e}")
                log.exception("Module d'outils %s non chargé", info.name)
        dossier_perso = dossier_perso or chemins.dossier_donnees() / "outils_perso"
        for fichier in sorted(dossier_perso.glob("*.py")) if dossier_perso.exists() else []:
            try:
                spec = importlib.util.spec_from_file_location(f"jarvis_perso_{fichier.stem}", fichier)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self._depuis_module(module)
            except Exception as e:  # noqa: BLE001
                self.erreurs.append(f"{fichier.name} : {e}")
        return self

    def schemas(self, noms: list[str] | None = None) -> list[dict]:
        return [o.schema() for n, o in self.outils.items() if noms is None or n in noms]

    def __getitem__(self, nom: str) -> Outil:
        return self.outils[nom]

    def __contains__(self, nom: str) -> bool:
        return nom in self.outils

    def hotes(self) -> set[str]:
        return {h for o in self.outils.values() for h in o.hotes}
