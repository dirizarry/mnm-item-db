"""Strip the custom MnM prefix from Unity Addressable bundles."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

UNITYFS = b"UnityFS"


def strip_mnm_header(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Return UnityFS payload and header metadata.

    Client bundles are prefixed with ``\\x00MnM\\x01`` (8 bytes) before UnityFS.
    """
    idx = data.find(UNITYFS)
    if idx < 0:
        raise ValueError("UnityFS signature not found")
    meta: dict[str, Any] = {"mnm_offset": idx, "raw_size": len(data)}
    if idx >= 8 and data[idx - 7 : idx] == b"MnM\x01":
        meta["mnm_magic"] = True
        meta["mnm_header"] = data[idx - 8 : idx].hex()
    # Unity bundle header: UnityFS\0 + version string
    tail = data[idx : idx + 128]
    m = re.search(rb"5\.x\.x\0(\d+\.\d+\.\d+f\d+)", tail)
    if m:
        meta["unity_version"] = m.group(1).decode("ascii", "ignore")
    return data[idx:], meta


def read_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    return strip_mnm_header(path.read_bytes())


def load_unity_env(path: Path):
    """Load a bundle or assets file via UnityPy after stripping MnM header."""
    import UnityPy

    stripped, meta = read_file(path)
    env = UnityPy.load(io.BytesIO(stripped))
    meta["stripped_size"] = len(stripped)
    return env, meta


def is_unity_bundle(path: Path) -> bool:
    try:
        head = path.read_bytes()[:32]
    except OSError:
        return False
    return b"UnityFS" in head or head.startswith(b"\x00MnM")
