# Monsters & Memories Item DB



A searchable item + monster database for [Monsters and Memories](https://monstersandmemories.miraheze.org),

built by extracting wiki templates into a normalized, relational dataset.



## Toolset map

The end-to-end architecture (data sources, capture, ingest, aggregation, wiki feedback) is

defined across these docs:

- [COMBAT-CAPTURE.md](COMBAT-CAPTURE.md) — combat/damage options; **Option C OCR prototype** (`mnm_combat_capture.py`)
- [PROVENANCE.md](PROVENANCE.md) — provenance channels, confidence/conflict scoring, and cross-user dedup rules (`mnm_provenance.py`, `mnm_crowd_aggregate.py`)
- [CLIENT.md](CLIENT.md) — the desktop control panel (`mnm_client.py`) + PyInstaller packaging + auto-update
- [DEPLOY.md](DEPLOY.md) — Phase A: host the static site + serverless ingest Worker (`workers/ingest/`)
- [SERVER.md](SERVER.md) — Phase B: hosted API + shared DB + trust engine + moderated wiki write-back (`server/`)
- [PRIVACY.md](PRIVACY.md) / [GOVERNANCE.md](GOVERNANCE.md) — opt-in sharing, deletion, anti-abuse, schema/DB versioning



## Pipeline



```

Category:Items  -> mnm_item_db.py   -> data/items.json

Category:NPCs   -> mnm_mob_db.py    -> data/monsters.json  ({{Namedmobpage}} only)

LocalLow logs   -> mine_local.py       -> data/ledger-*.json, site/stats/

                  build_relations.py -> data/game.db, drops.json  (item <-> mob links)

                  build_site.py      -> site/*.js (static UI)

```



### Extract items



```bash

pip install -r requirements.txt

python mnm_item_db.py --all

```



### Extract monsters



```bash

python mnm_mob_db.py --all          # ~700 combat mobs from Category:NPCs

python mnm_mob_db.py --pilot 50     # sample

```



### Local play analytics (repeatable)



One command for anyone with the game installed:



```bash

copy config\ledger.example.env config\ledger.env   # optional; edit MNM_LOCALLOW if needed

python mine_local.py

python -m http.server 8080   # then open http://localhost:8080/site/stats/

```



`mine_local.py` runs extraction → stats dashboard → upload bundle packaging.



| Step | Script | Output |

|------|--------|--------|

| Extract + parse logs | `mnm_ledger_db.py` (via `mine_local.py`) | `data/ledger-*.json`, `ledger-manifest.json` |

| Local dashboard | `build_ledger_site.py` | `site/stats/ledger-stats.js` |

| Upload stub | `mnm_ledger_upload.py` | `data/ledger-upload-payload.json` |

| Wiki merge (optional) | `build_relations.py` | `via_ledger` drop links in `data/game.db` |



Use `python mine_local.py --relations` to merge ledger drops into the wiki graph in the same run.



**Upload (stub):** copy `config/ledger.example.env` → `config/ledger.env`. When `MNM_UPLOAD_URL` is set, `python mine_local.py --upload` POSTs an aggregated bundle (no character names unless `MNM_UPLOAD_SHARE_CHARACTERS=1`). The stats page also has Copy JSON / Upload buttons for manual testing.



### Mine local play logs (details)



Reads `%LOCALAPPDATA%\\..\\LocalLow\\Niche Worlds Cult\\Monsters and Memories\\`:

- `Ledger/*_Character_*.json` — loot, kills, trades, vendor sells, harvests
- `Ledger/*_Social_*.json` — party events, party level-ups, shared kills/loot
- `Ledger/Archive/*.json` — rolled-up history snapshots
- `journal/<npc>` — NPC dialogue transcripts



```bash

python mine_local.py                    # recommended entry point

python mnm_ledger_db.py               # extract only

python mnm_ledger_db.py --path "D:\\..."   # custom install

python mnm_ledger_watch.py             # real-time session monitor (tail live ledgers)

```

### Real-time monitor

The game rewrites today's `Ledger/*.json` files on every event, each already
stamped with a sub-second timestamp. `mnm_ledger_watch.py` tails those files,
parses only new events, and tracks a live play session (kills/hr, coin/hr,
loot/hr, level progress). Every event is also stamped with its wall-clock
arrival time, so any future event type shipped without a timestamp still gets one.

```bash
python mnm_ledger_watch.py              # watch from now on (skip backlog)
python mnm_ledger_watch.py --backlog    # seed with today's existing events
python mnm_ledger_watch.py --once       # single catch-up pass, then exit
python mnm_ledger_watch.py --rebuild    # also refresh the full dashboard on idle lulls
```

Writes `data/ledger-live.json` (+ `site/stats/ledger-live.js`); the stats
dashboard shows a live session panel that polls it every few seconds while the
watcher runs.



| Output | Contents |

|--------|----------|

| `ledger-drops.json` | Item ↔ mob loot links (`act_13`) |

| `ledger-drop-rates.json` | Empirical drops-per-kill by mob/zone |

| `ledger-kills.json` | Your own kills (`act_14` corpses, `f07`==you), zone, copper |

| `ledger-kill-heatmap.json` | Kills by zone × day × character |

| `ledger-mobs.json` | Mob census + coin-per-kill stats (no level — see note) |

| `ledger-items.json` | Item IDs seen in play |

| `ledger-vendor-prices.json` | NPC sell prices (`act_24`) |

| `ledger-levelups.json` | Confirmed level-ups (`act_01`, Social) |

| `ledger-trades.json` | Player trades (`act_16`/`act_20`) |

| `ledger-party.json` | Party create/join/leave (`act_31`–`35`) |

| `ledger-journal.json` | NPC dialogue index |

| `ledger-report.txt` | Human summary |
| `ledger-loot.json` | Per-loot log (`act_13`) with looter vs owner (party loot) |
| `ledger-manifest.json` | Extraction metadata (repeat runs, upload id) |
| `ledger-live.json` | Live session snapshot from `mnm_ledger_watch.py` |
| `ledger-upload-payload.json` | Aggregated bundle for site ingest (gitignored) |



`build_relations.py` merges `ledger-drops.json` with wiki data (`via_ledger`).

> **Note on kills, coin, and "levels":** the ledger does **not** record mob
> levels. On `act_14` corpse events the `d11` field is exactly the copper that
> dropped (verified `d11 == copper` in 100% of corpses), so what earlier looked
> like a mob "level range" was really the coin-drop range. Stats now report
> coin-per-kill instead. Kills/coin/loot count **only your own actions**
> (`f07` == your character): your Social ledger also records partymates' kills
> and coin, which are excluded from personal totals (and deduped against the
> Character ledger) but kept separately for the party-loot view.
>
> **Coin — group total vs. your split (verified against in-game text):** each
> corpse has a **bulk** (`d11`/`d12`) that goes to one party member. The recipient
> is *random* — not whoever looted. From *your* ledger a corpse is one of:
> - **You won the bulk** → `npc_corpse` with `f07` == you; `d12` is the bulk
>   (counted in `own_bulk`).
> - **A mate won the bulk** → `party_split`; `d12` is *their* bulk (`others_bulk`)
>   and `d15` is **your** small split of the same corpse (`split_received`,
>   e.g. "Weirdbob loots 1s 11c … you receive 1 copper as your split").
>
> So `group_total = own_bulk + others_bulk` (all the group looted; bulk-dominated,
> slightly under since other members' splits aren't in your ledger) and
> `my_split = own_bulk + split_received` (your cut). `ledger-coin.json` reports
> these per character plus `my_share`. Notes: an earlier bug summed *other* members'
> bulk as yours. **No event ever populates the gold or platinum slots** — all coin
> is silver/copper, so totals are capped at gold (1g = 100c, 1s = 10c) and never
> rolled into plat. These are lifetime *flows* (earned and spent), not coin-on-hand;
> the ledger has no wallet-balance event.

Open **`site/stats/index.html`** for local charts (kills/day, heatmap, drop rates, level-ups) and upload controls. The **Live session** panel updates every few seconds while `mnm_ledger_watch.py` is running; serve the folder over HTTP (e.g. `python -m http.server` in `site/`) so it can poll the snapshot.



### Client reverse engineering (static)



Indexes the installed game client (`%LOCALAPPDATA%/Monsters & Memories/mnm/`): strips the custom `MnM` bundle header, catalogs Unity Addressables, ranks large `MonoBehaviour` blobs (likely Odin-serialized data tables), and crosswalks ledger `item_hid` values against bundles.



```bash

pip install -r requirements-client.txt

python mnm_client_db.py --all

```



Outputs under `data/client/` (`bundle-index.json`, `asset-candidates.json`, `ids-crosswalk.json`, etc.). See `CLIENT-RE.md` for phase status. Full item stat extraction (Phase 4 Odin deserialize) is not automated yet.



### Build relations + site



```bash

python normalize_data.py --backup     # optional: persist zones[] to JSON + wiki queue

python build_relations.py           # merges item drops + mob loot -> game.db

python build_site.py                # bundles site/items.js, monsters.js, drops.js

```



### Zone normalization



Wiki mob `zone=` fields and item `dropsfrom=` blocks use inconsistent formatting
(`[[Night Harbor]]` vs plain text, NPC names listed as zones, etc.). The pipeline
normalizes at build time via `data/zone_canonical.json` and `mnm_zones.py`.



| Step | Command |

|------|---------|

| Persist normalized JSON | `python normalize_data.py --backup` |

| Audit report | `data/zones-audit.txt` (also written by `build_relations.py`) |

| Wiki fix queue | `data/zones-wiki-queue.json` |

| Generate wiki patches | `python gen_wiki_zone_fixes.py --all` |

| Push patches | `python push_wiki_batch.py data/wiki-fixes/zones/mob-zone-manifest.json` |



Monsters store `zones: []` (all zones) plus `zone` (primary). `Unknown` is kept
as a displayable zone when the wiki says so.



### Unified SQLite (`data/game.db`)



| Table | Purpose |

|-------|---------|

| `items` | Item summary |

| `monsters` | Mob stats, zone, level |

| `drops` | **Relational** item ↔ mob links (`via_mob`, `via_item`, `via_ledger`, `loot_kind`, `zone`) |

| `zones` | Zone index (mob/drop counts) |



Drop links are merged from wiki mob loot lists, item `dropsfrom` fields, and local ledger loot events when `ledger-drops.json` exists.



## Site



Open `site/index.html` — **Items** and **Monsters** tabs with cross-links (click loot → item search; `MNM_showMob` / `MNM_showItem`).



## Wiki corrections



```bash

python push_wiki.py --page "Item Name" --file data/wiki-fixes/your-fix.wiki

```



Credentials: `%USERPROFILE%\.mnm-wiki\wiki-credentials.env`



## Data source



Unofficial fan tool. Item data from `{{ItemBox}}`, monster data from `{{Namedmobpage}}` on the M&M wiki.


