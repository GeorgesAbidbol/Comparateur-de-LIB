"""Client GDTF Share (https://gdtf-share.com) : connexion, liste, téléchargement.

Testé contre le vrai site le 2026-11-11 : connexion, liste (~13 500 entrées,
champ « uploader » = « Manuf. » ou « User »), téléchargement et ouverture des
GDTF Robin iTetra2, Nando 502 et Color Strike M. Points d'accès :
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
    uploader: str = ""  # « Manuf. » pour un fichier du fabricant, « User » pour un envoi d'utilisateur

    @property
    def official(self) -> bool:
        return self.uploader.strip().lower().startswith("manuf")

    @property
    def stamp(self) -> float:
        try:
            return float(self.last_modified)
        except ValueError:
            return 0.0

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
            uploader=str(d.get("uploader", "")),
        )


def official(entries: list[ShareEntry]) -> list[ShareEntry]:
    """Les fichiers des fabricants seulement. Si la liste ne dit pas qui a envoyé quoi, on garde tout."""
    if not any(e.uploader for e in entries):
        return list(entries)
    return [e for e in entries if e.official]


def latest(entries: list[ShareEntry]) -> list[ShareEntry]:
    """Une ligne par fixture : sa révision la plus récente."""
    best: dict[tuple[str, str], ShareEntry] = {}
    for e in entries:
        key = (e.manufacturer.lower(), e.fixture.lower())
        if key not in best or e.stamp >= best[key].stamp:
            best[key] = e
    return sorted(best.values(), key=lambda e: (e.manufacturer.lower(), e.fixture.lower()))


def search(entries: list[ShareEntry], text: str) -> list[ShareEntry]:
    """Filtre local : tous les mots doivent apparaître dans fabricant + nom."""
    words = text.lower().split()
    return [e for e in entries
            if all(w in f"{e.manufacturer} {e.fixture}".lower() for w in words)]


def _system_certificates() -> None:
    """Certificats du système (Windows) pour HTTPS, en plus de ceux livrés avec l'appli :
    un antivirus ou un réseau qui inspecte HTTPS ne casse plus la connexion. Sans le module
    `truststore`, on garde ceux de `requests`."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass


def explain(exc: Exception) -> str:
    """Phrase lisible pour une erreur de connexion (réseau, certificat, site en panne…)."""
    if isinstance(exc, ShareError):
        return str(exc)
    name, text = type(exc).__name__, str(exc)
    if "SSL" in name or "CERTIFICATE" in text.upper():
        hint = "certificat HTTPS refusé (antivirus ou réseau qui filtre HTTPS ?)"
    elif "Timeout" in name:
        hint = "le site ne répond pas (réseau lent ou site en panne)"
    elif "Proxy" in name:
        hint = "proxy du réseau refusé"
    elif "Connection" in name:
        hint = "pas de connexion au site (pas d'internet, pare-feu, ou site en panne)"
    else:
        hint = "erreur inattendue"
    return f"{hint} — {name}: {text[:300]}"


class GdtfShareClient:
    def __init__(self, user: Optional[str] = None, password: Optional[str] = None):
        import requests  # import tardif : le reste de l'appli fonctionne sans
        _system_certificates()

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


def selftest() -> tuple[bool, list[str]]:
    """Contrôle de l'exe à la fabrication (« --selftest-share ») : certificats, coffre Windows,
    et le site GDTF Share joignable. Le site est interrogé avec un compte bidon : un refus
    propre (« connexion refusée ») prouve que réseau, HTTPS et lecture de la réponse marchent."""
    ok, out = True, []
    try:
        import truststore  # noqa: F401
        out.append("certificats système : truststore présent")
    except Exception as exc:
        out.append(f"certificats système : absent ({exc})")
    from . import coffre
    kr = coffre._backend()
    if kr is None:
        ok = False
        out.append("coffre : module keyring absent")
    else:
        name = type(kr.get_keyring()).__module__ + "." + type(kr.get_keyring()).__name__
        out.append(f"coffre : {name}")
        try:
            kr.set_password("Banane Pot - essai", "essai", "secret-essai")
            good = kr.get_password("Banane Pot - essai", "essai") == "secret-essai"
            kr.delete_password("Banane Pot - essai", "essai")
            out.append("coffre : écriture/lecture/effacement OK" if good else "coffre : relu différent")
            ok = ok and good
        except Exception as exc:
            ok = False
            out.append(f"coffre : ÉCHEC {type(exc).__name__}: {exc}")
    try:
        GdtfShareClient("banane-pot-selftest@example.invalid", "pas-un-vrai-mot-de-passe").login()
        out.append("site : connexion acceptée ?! (inattendu)")
    except ShareError as exc:
        good = "connexion refusée" in str(exc)
        ok = ok and good
        out.append(f"site : joignable, compte bidon refusé comme prévu ({exc})" if good
                   else f"site : réponse inattendue ({exc})")
    except Exception as exc:
        ok = False
        out.append(f"site : ÉCHEC {explain(exc)}")
    return ok, out
