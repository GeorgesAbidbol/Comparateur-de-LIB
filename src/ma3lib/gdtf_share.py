"""Client GDTF Share (https://gdtf-share.com) : connexion, liste, téléchargement.

NON TESTÉ en réel : le site n'est pas joignable depuis l'environnement de dev.
Les points d'accès suivent l'API publique documentée par GDTF Share :
  POST apis/public/login.php        {"user": ..., "password": ...}
  GET  apis/public/getList.php      -> {"result": true, "list": [...]}
  GET  apis/public/downloadFile.php?rid=<id>
Il faut un compte GDTF Share. Les identifiants ne sont jamais écrits sur disque
par ce module : on les lit dans GDTF_SHARE_USER / GDTF_SHARE_PASSWORD ou on
les demande.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BASE_URL = "https://gdtf-share.com/apis/public/"
TIMEOUT = 30


class ShareError(Exception):
    pass


@dataclass
class ShareEntry:
    rid: int
    manufacturer: str
    fixture: str
    revision: str
    modes: list[str]
    last_modified: str
    raw: dict

    @classmethod
    def from_json(cls, d: dict) -> "ShareEntry":
        modes = d.get("modes") or []
        return cls(
            rid=int(d.get("rid", 0)),
            manufacturer=str(d.get("manufacturer", "")),
            fixture=str(d.get("fixture", "")),
            revision=str(d.get("revision", "")),
            modes=[m.get("name", "") if isinstance(m, dict) else str(m) for m in modes],
            last_modified=str(d.get("lastModified", "")),
            raw=d,
        )


def search(entries: list[ShareEntry], text: str) -> list[ShareEntry]:
    """Filtre local : tous les mots doivent apparaître dans fabricant + nom."""
    words = text.lower().split()
    return [e for e in entries
            if all(w in f"{e.manufacturer} {e.fixture}".lower() for w in words)]


class GdtfShareClient:
    def __init__(self, user: Optional[str] = None, password: Optional[str] = None):
        import requests  # import tardif : le reste de l'appli fonctionne sans

        self.user = user or os.environ.get("GDTF_SHARE_USER", "")
        self.password = password or os.environ.get("GDTF_SHARE_PASSWORD", "")
        self.session = requests.Session()
        self.logged_in = False

    def login(self) -> None:
        if not self.user or not self.password:
            raise ShareError("identifiants GDTF Share manquants")
        r = self.session.post(BASE_URL + "login.php",
                              json={"user": self.user, "password": self.password}, timeout=TIMEOUT)
        data = _json(r)
        if not data.get("result"):
            raise ShareError(f"connexion refusée : {data.get('error') or r.status_code}")
        self.logged_in = True

    def list(self) -> list[ShareEntry]:
        self._ensure_login()
        r = self.session.get(BASE_URL + "getList.php", timeout=TIMEOUT * 4)
        data = _json(r)
        if not data.get("result"):
            raise ShareError(f"liste indisponible : {data.get('error') or r.status_code}")
        return [ShareEntry.from_json(d) for d in data.get("list", [])]

    def download(self, entry: ShareEntry, dest_dir: Path) -> Path:
        self._ensure_login()
        r = self.session.get(BASE_URL + "downloadFile.php", params={"rid": entry.rid}, timeout=TIMEOUT * 4)
        if r.status_code != 200 or not r.content.startswith(b"PK"):
            raise ShareError(f"téléchargement rid={entry.rid} échoué ({r.status_code})")
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = _safe(f"{entry.manufacturer}@{entry.fixture}@{entry.revision}") + ".gdtf"
        path = dest_dir / name
        path.write_bytes(r.content)
        return path

    def _ensure_login(self) -> None:
        if not self.logged_in:
            self.login()


def _json(response) -> dict:
    try:
        return response.json()
    except ValueError as exc:
        raise ShareError(f"réponse inattendue du serveur ({response.status_code})") from exc


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "fixture"
