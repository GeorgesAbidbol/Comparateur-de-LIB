"""Compte GDTF Share retenu dans le coffre du système (Gestionnaire d'identifiants de Windows),
choix de Jo du 11/11/2026. Le mot de passe y est gardé chiffré par Windows ; il n'est jamais
écrit dans un fichier de l'appli ni dans le dépôt. Sans le module `keyring`, rien n'est retenu.
"""

from __future__ import annotations

import json
from typing import Optional

SERVICE = "Banane Pot - GDTF Share"
ENTRY = "compte"


def _backend():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def available(backend=None) -> bool:
    return (backend if backend is not None else _backend()) is not None


def load(backend=None) -> Optional[tuple[str, str]]:
    """(e-mail, mot de passe) retenus, ou None."""
    kr = backend if backend is not None else _backend()
    if kr is None:
        return None
    try:
        data = json.loads(kr.get_password(SERVICE, ENTRY) or "null")
        return (data["user"], data["password"]) if data else None
    except Exception:
        return None


def save(user: str, password: str, backend=None) -> bool:
    kr = backend if backend is not None else _backend()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE, ENTRY, json.dumps({"user": user, "password": password}))
        return True
    except Exception:
        return False


def forget(backend=None) -> None:
    kr = backend if backend is not None else _backend()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, ENTRY)
    except Exception:
        pass
