# MnM Item DB — Desktop Client (Phase A)

A one-window control panel that wraps the existing pipeline so players don't need a
terminal. It auto-discovers your Monsters & Memories logs, mines analytics, runs a live
session monitor, opens the local dashboard, and (optionally) submits aggregated data.

## Run from source

```
pip install -r requirements.txt
python mnm_client.py
```

What the buttons do:

| Button | Action |
|---|---|
| Mine logs now | Extract kills/loot/coin/XP from your Ledger and rebuild the stats dashboard |
| Start/Stop live watch | Tail today's logs while you play; stats update every couple seconds |
| Open dashboard | Serve `site/stats/` on `127.0.0.1` and open it in your browser |
| Rebuild DB | Re-link items/mobs/drops into `data/game.db` with provenance + confidence |
| Submit data | Build the privacy-gated `mnm-ledger-upload/v2` payload and POST it if a submit URL is set |
| **Combat window OCR** | Read the in-game combat chat window via screen OCR → damage/healing totals (see below) |
| Settings | Logs folder, submit endpoint, **combat capture region**, OCR interval |
| Check for updates | Compare your version to the published manifest |

### Combat OCR (built into the control panel)

Requires optional deps: `pip install -r requirements-combat.txt`

1. In-game: route Combat/Ability/Buff/Death messages to the **combat** chat window; use large font + high contrast.
2. In the control panel: **Pick on screen…** (drag around the combat window) or **Estimate…** in Settings.
3. **Test OCR once** — verify text is captured before a long session.
4. **Start combat OCR** while playing — live **Damage out/in** and **Heal out/in** counters update in the panel.
5. Parsed events are saved to `data/combat-events.json` and `data/combat-live.json` in your workspace.

You can run ledger **live watch** and **combat OCR** at the same time.

Log auto-discovery uses the standard path
`%USERPROFILE%\AppData\LocalLow\Niche Worlds Cult\Monsters and Memories`; override it in
Settings or via `MNM_LOCALLOW`.

## Build a standalone exe

```
pip install pyinstaller
python build_client.py            # or: pyinstaller mnm_client.spec
```

Output: `dist/MnMItemDB/` (onedir). Zip and share that folder; users run `MnMItemDB.exe`.

When frozen, the app keeps read-only bundled resources (the UI + reference data) next to the
exe and writes all per-user state (settings, mined data, dashboard) to a writable workspace at
`%LOCALAPPDATA%\MnMItemDB`, so it never needs admin rights. `mnm_paths.py` centralizes this and
retargets the pipeline modules' output directories at startup.

## Auto-update

`mnm_updater.py` fetches a small JSON manifest and compares versions:

```json
{ "version": "0.4.0", "url": "https://github.com/OWNER/mnm-item-db/releases", "notes": "What's new" }
```

If a newer version is advertised, the app prompts and opens the download page. It does **not**
silently replace the binary (platform-specific and risky). Set the manifest URL in Settings
(`update_url`) — host it next to the static site or as a GitHub raw file.

## Privacy

Submissions are aggregated and **anonymous by default** — character names are only included if
you tick "Share character names". See [PRIVACY.md](PRIVACY.md) for exactly what is sent.
