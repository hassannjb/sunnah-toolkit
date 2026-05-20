"""Bearer-token auth: load keys from a YAML file, authenticate requests.

Open tier: no keys configured OR no token sent → ("open", None).
Keyed tier: token matches a configured key → ("keyed", name).
Invalid: token sent but unknown → 401.

Rate limiting is at the edge (Cloudflare). This module only identifies callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_keys: dict[str, str] = {}
_security = HTTPBearer(auto_error=False)


def load_keys(path: Path | str | None) -> None:
    global _keys
    _keys = {}
    if path is None:
        return
    p = Path(path)
    if not p.exists():
        return
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for entry in raw.get("keys", []):
        token = entry.get("key")
        name = entry.get("name") or "unnamed"
        if token:
            _keys[str(token)] = str(name)


def authenticate(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> tuple[str, str | None]:
    if not _keys or creds is None:
        return ("open", None)
    name = _keys.get(creds.credentials)
    if name is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")
    return ("keyed", name)
