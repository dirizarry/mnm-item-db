# Wiki data issues catalog

Running list of Monsters & Memories wiki data problems found while building the
item DB. **No edits made yet — cataloging only** (per decision 2026-06-14).
When ready, fixes can be pushed via `push_wiki.py`.

Last updated: 2026-06-14 (item crawl = 2,805 items)

---

## A. Fixed on our side (no wiki edit needed)

- **Self-referential recipes** — our parser was capturing the recipe "Yield" line
  as an ingredient (item listed as its own component). Fixed in `mnm_item_db.py`
  (skip Yield lines + self-name). 0 remaining.
- **Zone name normalization** — mob `[[Zone]]` markup, underscores, multi-zone
  strings, and item `dropsfrom` misclassification (NPC names as zones). Fixed in
  `mnm_zones.py` + `normalize_data.py`. Wiki patches optional via
  `gen_wiki_zone_fixes.py` (see `data/wiki-fixes/zones/README.md`).

## B. Our parser gaps (pending, no wiki edit)

- **Alternate item-box formats** not yet parsed (~8 items):
  - `{{#invoke:ItemBox|main ...}}` — e.g. **Nestguard Wristwraps** (real item: WRIST, AC 4, STA 2, WIS 2).
  - Old HTML `<div class="item-box">` — e.g. **Icon of the Matswar** (quest item).
  - Action: extend `extract_itembox` to recognize these. Low priority (~8 items).

## C. Genuine wiki bad data (needs decision before editing)

### C6. Zone / dropsfrom formatting (optional wiki cleanup)
- **~220 mob pages** — `Namedmobpage|zone=` uses `[[Wiki Links]]` instead of plain
  text. Pipeline normalizes; `gen_wiki_zone_fixes.py --mobs` generates patches.
- **~98 item pages** — `dropsfrom` lists NPC/mob names on non-bullet lines (parsed
  as zones). Pipeline reroutes to `drops_mobs`; `gen_wiki_zone_fixes.py --items`
  generates patches.
- **Convention:** zones plain or `[[Zone]]` on unbulleted lines; mobs on `*` lines.
  Multi-zone mobs: comma-separated plain names in `zone=`.

### C1. Miscategorized non-items in `Category:Items`
Pulled in by unescaped example/template code; also appear in `Item Box Bucket Failure`.
- `User talk:Kiyoshi-dono` — a talk page; has Item/Equipment/Bags categories from a
  pasted code example. Fix: wrap example in `<nowiki>`/`<pre>`.
- `Cloth Scraps Quest` — a `{{Quest}}` page miscategorized as Items/Equipment/Bags.
- Likely also: `Dealing with the Blacktide Orcs`, `Pelts for the Festival`,
  `The Joy of Surveying`, `Advanced Surveying Volume I` (quest/book pages).

### C2. Wiki's own broken-page backlog
- **`Category:Item Box Bucket Failure` = 570 pages.** Maintainer-flagged item pages
  where the item-box data store failed. Needs sampling to find the common breakage
  before any bulk fix. (Do NOT bulk-edit blindly.)
- **`Category:Old Itembox Items` = 1,600 pages.** Mid-migration to a new item-box
  format. These mostly still parse (our "freeform" dialect).

### C3. Name / title typos (would require page moves)
- `T reatment Kit` (spurious space) — note: a follow-up API check returned "missing",
  so the exact title may differ; verify before acting.
- Source-data typos seen in item names: `Ironhide Gridle` (Girdle),
  `Obscure Broardsword` (Broadsword).

### C4. Data gaps (cannot fix without info — candidates for the screenshot parser)
- **366 equippable items with NO source data** (e.g. Bronze Shortsword, Buckler,
  Cleaver, Copper Shortsword) — likely vendor/starter, undocumented.
- **Drops with known zone but unknown mob** (e.g. Bandit Chain Boots → Scarwood, mob `?`).
- **604 items total** classified `source_types = ["unknown"]`.
- Recipes lack **yields** (we assume 1 → material totals are upper bounds).

### C5. Probably-correct-but-looks-odd (leave alone)
- `Copper Bar ↔ Copper Scraps` reciprocal recipe — likely a real salvage/smelt loop.
  Our material rollup breaks the cycle (treats Copper Scraps as raw), so no fix needed.

---

## Counts snapshot (2026-06-14)
- Items crawled: 2,805 (1,837 equippable)
- Source: dropped 1,301 · crafted 599 (580 with components) · quest 464 · starter 225 · unknown 604
- Wiki flags: Item Box Bucket Failure 570 · Old Itembox Items 1,600
