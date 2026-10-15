"""Garde-fou des écritures : aperçu + jeton à usage unique, puis confirmation explicite.

Aucune écriture (import de noms, association, retrait) ne part sans passer par ici, et rien ne part
du tout tant que MACLASSE_ENABLE_WRITES n'est pas à 1.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import SETTINGS

ALLOWED_ACTIONS = {"importer_noms", "associer_noms", "retirer_noms"}
TOKEN_TTL = 15 * 60


@dataclass
class Pending:
    action: str
    apercu: dict[str, Any]
    run: Callable[[], dict[str, Any]]
    created: float = field(default_factory=time.time)


class WriteGate:
    def __init__(self) -> None:
        self._pending: dict[str, Pending] = {}

    def prepare(self, action: str, apercu: dict[str, Any], run: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        if not SETTINGS.enable_writes:
            raise RuntimeError("Écritures désactivées (MACLASSE_ENABLE_WRITES=1 pour les autoriser)")
        if action not in ALLOWED_ACTIONS:
            raise RuntimeError(f"Action non autorisée : {action}")
        token = secrets.token_urlsafe(12)
        self._pending[token] = Pending(action, apercu, run)
        return {"jeton": token, "action": action, "apercu": apercu,
                "consigne": "Montrer cet aperçu à l'utilisateur ; n'appeler maclasse_write_confirm qu'après son accord explicite."}

    def confirm(self, token: str) -> dict[str, Any]:
        p = self._pending.pop(token, None)
        if p is None:
            raise RuntimeError("Jeton inconnu ou déjà utilisé")
        if time.time() - p.created > TOKEN_TTL:
            raise RuntimeError("Jeton expiré : refaire la préparation")
        return {"action": p.action, **p.run()}

    def cancel(self, token: str) -> bool:
        return self._pending.pop(token, None) is not None

    def pending(self) -> list[dict[str, Any]]:
        return [{"jeton": t, "action": p.action, "age_s": int(time.time() - p.created)} for t, p in self._pending.items()]


GATE = WriteGate()
