# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MnM Item DB is a fan-made toolset for the MMORPG "Monsters and Memories." It extracts data from the game wiki and local play logs to build a searchable item/monster database with drop links, then provides both a static web site and a desktop client for players.

## Common Commands

### Setup & Dependencies
```bash
pip install -r requirements.txt           # Core wiki extraction
pip install -r requirements-client.txt    # Client RE (UnityPy)
pip install -r requirements-combat.txt    # Combat OCR (Windows only)
pip install -r server/requirements.txt    # Phase B API server
```

### Data Pipeline
```bash
python mnm_item_db.py --all               # Extract items from wiki
python mnm_mob_db.py --all                # Extract monsters from wiki
python mine_local.py                      # Extract local play logs (ledger)
python build_relations.py                 # Merge all sources -> data/game.db
python build_site.py                      # Generate site/*.js bundles
```

### Desktop Client
```bash
python mnm_client.py                      # Run from source
pip install pyinstaller && python build_client.py  # Build dist/MnMItemDB/
```

### Server (Phase B)
```bash
export MNM_ADMIN_TOKEN=$(openssl rand -hex 16)
uvicorn server.app:app --port 8000
```

### Testing
```bash
python -m pytest tests/                   # Run all tests
python -m pytest tests/test_provenance.py # Run single test file
python -m pytest tests/test_provenance.py::test_score_edge_confirmed  # Single test
```

### Wiki Operations
```bash
python push_wiki.py --page "Item Name" --file data/wiki-fixes/your-fix.wiki
```
Credentials: `%USERPROFILE%\.mnm-wiki\wiki-credentials.env`

## Architecture

### Data Flow
```
Wiki (Category:Items, Category:NPCs)
        ↓
mnm_item_db.py / mnm_mob_db.py  →  data/items.json, monsters.json
        ↓
LocalLow/Ledger/*.json  →  mnm_ledger_db.py  →  data/ledger-*.json
        ↓
build_relations.py  →  data/game.db (SQLite: items, monsters, drops, zones)
        ↓
build_site.py  →  site/*.js (static UI)
```

### Key Modules

**Data Extraction:**
- `mnm_item_db.py` / `mnm_mob_db.py` - Wiki template parsers
- `mnm_ledger_db.py` / `mnm_ledger_parse.py` - Parse game Ledger JSON files
- `mnm_client_db.py` - Unity client RE (bundle headers, asset catalog)

**Provenance & Trust (`mnm_provenance.py`):**
- Drop edges have channels: `via_mob`, `via_item`, `via_client`, `via_ledger`, `via_crowd`
- `score_edge()` computes confidence (noisy-OR model) and status (`confirmed`, `crowd_candidate`, `wiki_corroborated`, `wiki_unconfirmed`)
- `crowd_candidate` = observed in play but not on wiki → wiki gap to fix

**Cross-User Dedup:**
- `kill_token()` / `loot_token()` produce 20-char sha256 prefixes for dedup
- Aggregator unions tokens across users (not sums) to prevent double-counting

**Desktop Client (`mnm_client.py`):**
- Tkinter GUI wrapping the pipeline
- `mnm_paths.py` handles frozen (PyInstaller) vs source paths
- Writes user data to `%LOCALAPPDATA%\MnMItemDB` when frozen

**Combat Capture (Option C: OCR / Option F: Memory):**
- `mnm_combat_ocr.py` - Screen capture + Windows OCR or Tesseract
- `mnm_combat_text.py` - EQ-style combat line parser
- `mnm_combat_memory.py` - Read combat text from mnm.exe process memory
- `mnm_combat_watch.py` - Live capture loop

**Server (Phase B in `server/`):**
- FastAPI ingest + admin endpoints
- `server/aggregate.py` - Recomputes dataset from crowd payloads
- SQLite with `schema_version` migrations (swap to Postgres for production)

### Deployment

**Static Site:** GitHub Pages via `.github/workflows/deploy-site.yml` - rebuilds on push to main

**Ingest Worker (Phase A):** `workers/ingest/` - Cloudflare Worker + R2 bucket

**Server (Phase B):** `server/` - FastAPI + SQLite/Postgres

### Environment Variables
- `MNM_LOCALLOW` - Override game log path
- `MNM_UPLOAD_URL` / `MNM_UPLOAD_TOKEN` - Submit endpoint
- `MNM_UPLOAD_SHARE_CHARACTERS` - Include character names in uploads (0/1)
- `MNM_ADMIN_TOKEN` - Required for server admin endpoints
- `MNM_WORKSPACE` - Override writable data directory

### Zone Normalization
Wiki zone fields are inconsistent. `mnm_zones.py` + `data/zone_canonical.json` normalize at build time. Audit: `data/zones-audit.txt`. Fix generation: `python gen_wiki_zone_fixes.py --all`.

### Upload Payload Schema
Clients send `mnm-ledger-upload/v2` with `token_scheme: mnm-dedup/v1`. The `dedup_tokens` arrays enable cross-user dedup. v1 clients (no tokens) fall back to raw count sums.
