"""Lightweight update check for the desktop client.

Queries a small JSON manifest (hosted next to the static site or on GitHub) and
compares the advertised version to the running one. We deliberately do NOT
auto-replace the binary — that is risky and platform-specific. Instead we surface
"an update is available" plus a download URL the user can click.

Manifest shape (latest-version.json):
    {"version": "0.4.0", "url": "https://.../releases", "notes": "..."}
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from mnm_version import __version__


@dataclass
class UpdateInfo:
    current: str
    latest: str
    update_available: bool
    url: str = ""
    notes: str = ""
    error: str = ""


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in str(v).strip().lstrip("v").split("."):
        num = "".join(c for c in chunk if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def check_for_update(manifest_url: str, timeout: float = 8.0) -> UpdateInfo:
    info = UpdateInfo(current=__version__, latest=__version__, update_available=False)
    if not manifest_url or "OWNER" in manifest_url:
        info.error = "update_url not configured"
        return info
    try:
        resp = requests.get(manifest_url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        info.error = str(exc)
        return info

    latest = str(data.get("version", "")) or __version__
    info.latest = latest
    info.url = data.get("url", "")
    info.notes = data.get("notes", "")
    info.update_available = _parse_version(latest) > _parse_version(__version__)
    return info
