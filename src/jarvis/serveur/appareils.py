"""Appareils appairés (SEC-06, SEC-10, SEC-13) : code à usage unique, jeton par appareil, révocation.

Seule l'empreinte SHA-256 des jetons est stockée. Le jeton du PC lui-même (interface locale)
est régénéré à chaque démarrage et ne quitte pas la machine.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from jarvis import chemins

DUREE_CODE_S = 300
ESSAIS_MAX = 5


def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


class Appareils:
    def __init__(self, chemin: Path | None = None):
        self.chemin = chemin or chemins.dossier_donnees() / "appareils.json"
        self._verrou = threading.Lock()
        self._code: tuple[str, float] | None = None
        self._essais = 0
        self.jeton_local = secrets.token_urlsafe(32)  # interface ouverte sur le PC même
        self.derniere_activite: dict[str, float] = {}

    def _lire(self) -> dict:
        return json.loads(self.chemin.read_text("utf-8")) if self.chemin.exists() else {}

    def _ecrire(self, donnees: dict) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), "utf-8")

    def nouveau_code(self) -> str:
        """Code à 6 chiffres affiché sur le PC, valable 5 minutes, utilisable une fois."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._code = (code, time.monotonic() + DUREE_CODE_S)
        self._essais = 0
        return code

    def appairer(self, code: str, nom: str, type_: str = "navigateur") -> str | None:
        with self._verrou:
            if not self._code or time.monotonic() > self._code[1] or self._essais >= ESSAIS_MAX:
                self._code = None
                return None
            self._essais += 1
            if not hmac.compare_digest(code.strip(), self._code[0]):
                return None
            self._code = None
            jeton = secrets.token_urlsafe(32)
            ident = secrets.token_hex(4)
            donnees = self._lire()
            donnees[ident] = {"nom": nom[:60] or "appareil", "type": type_, "empreinte": _empreinte(jeton),
                              "appaire": datetime.now().isoformat(timespec="seconds"), "biometrie": type_ == "android"}
            self._ecrire(donnees)
            return f"{ident}.{jeton}"

    def authentifier(self, jeton: str | None) -> dict | None:
        """Renvoie l'appareil (avec son identifiant) ou None."""
        if not jeton:
            return None
        if hmac.compare_digest(jeton, self.jeton_local):
            self.derniere_activite["pc"] = time.time()
            return {"id": "pc", "nom": "PC", "type": "pc"}
        ident, _, secret = jeton.partition(".")
        appareil = self._lire().get(ident)
        if appareil and hmac.compare_digest(appareil["empreinte"], _empreinte(secret)):
            self.derniere_activite[ident] = time.time()
            return {"id": ident, **{k: v for k, v in appareil.items() if k != "empreinte"}}
        return None

    def lister(self) -> list[dict]:
        return [{"id": i, **{k: v for k, v in a.items() if k != "empreinte"},
                 "derniere_activite": self.derniere_activite.get(i)} for i, a in self._lire().items()]

    def revoquer(self, ident: str) -> bool:
        with self._verrou:
            donnees = self._lire()
            if donnees.pop(ident, None) is None:
                return False
            self._ecrire(donnees)
            return True

    def appareil_actif(self, fenetre_s: float = 600) -> str | None:
        """MULTI-02 : l'appareil utilisé le plus récemment (dans la fenêtre donnée)."""
        recents = {i: t for i, t in self.derniere_activite.items() if time.time() - t < fenetre_s}
        return max(recents, key=recents.get) if recents else None
