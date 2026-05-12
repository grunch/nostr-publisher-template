#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request

DEFAULT_NOTION_VERSION = "2022-06-28"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs into the current process environment.

    Blank lines and comments are ignored. Existing environment variables are
    preserved.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        os.environ[key] = value


def notion_request(method: str, url: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY is not set")

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Notion-Version": os.environ.get("NOTION_VERSION", DEFAULT_NOTION_VERSION),
        "User-Agent": "mostro-nostr-publisher-template",
    }

    req = request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Notion API request failed ({exc.code} {exc.reason}): {body}") from exc
