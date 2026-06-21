# PyInstaller spec for the MnM Item DB desktop client.
#   pip install pyinstaller
#   pyinstaller mnm_client.spec
# Produces dist/MnMItemDB/ (onedir). Zip and share that folder.

from pathlib import Path

block_cipher = None
ROOT = Path(".").resolve()

# The pipeline modules are imported lazily inside functions, so PyInstaller's static
# analysis misses them — declare them explicitly.
HIDDEN = [
    "mnm_ledger_db", "mnm_ledger_parse", "mnm_ledger_watch", "mnm_ledger_upload",
    "mnm_ledger_config", "mnm_local", "mnm_zones", "mnm_provenance",
    "mnm_crowd_aggregate", "build_ledger_site", "build_relations", "build_site",
    "normalize_data", "mnm_updater", "mnm_version", "mnm_paths", "requests",
    "mnm_chat_windows", "mnm_combat_text", "mnm_combat_ocr", "mnm_combat_watch",
    "mnm_region_selector",
    "mnm_game_window",
    "mnm_combat_channels",
    "mnm_combat_pvp",
    "mnm_combat_streams",
    "mnm_combat_filter_dialog",
    "mss", "winrt.windows.media.ocr", "winrt.windows.graphics.imaging",
]

# Bundle read-only resources: the static UI and the data files the parsers need.
DATAS = [("site", "site")]
for name in ("zone_canonical.json", "items.json", "monsters.json", "drops.json", "zones.json",
             "combat-filter-ui.json", "combat-channels.json"):
    p = ROOT / "data" / name
    if p.exists():
        DATAS.append((str(p), "data"))

a = Analysis(
    ["mnm_client.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "pandas", "matplotlib"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MnMItemDB",
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="MnMItemDB")
