"""Load optional local ledger / upload settings from config/ledger.env."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent
ENV_PATH = ROOT / "config" / "ledger.env"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def ledger_settings() -> dict[str, str | bool | None]:
    """Merge config/ledger.env with process environment."""
    file_vals = _parse_env_file(ENV_PATH)
    env = {**file_vals, **{k: v for k, v in os.environ.items() if k.startswith("MNM_")}}

    share = str(env.get("MNM_UPLOAD_SHARE_CHARACTERS", "0")).lower() in {"1", "true", "yes"}
    share_hc = str(env.get("MNM_UPLOAD_SHARE_HARDCORE", "0")).lower() in {"1", "true", "yes"}
    return {
        "locallow": env.get("MNM_LOCALLOW"),
        "upload_url": env.get("MNM_UPLOAD_URL"),
        "upload_token": env.get("MNM_UPLOAD_TOKEN"),
        "share_characters": share,
        "share_hardcore": share_hc,
    }
