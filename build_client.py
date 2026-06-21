#!/usr/bin/env python3
"""Build the desktop client into a distributable folder with PyInstaller.

    pip install pyinstaller
    python build_client.py

Output: dist/MnMItemDB/  (zip this and share it)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: pip install pyinstaller")
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "mnm_client.spec"]
    print("Running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc == 0:
        print("\nBuilt dist/MnMItemDB/ — zip that folder and share it.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
