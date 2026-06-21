# Combat / Damage / Healing Capture — Findings & Decision

Status: **Discovery spike complete (2026-06-19).** This doc settles how (and whether) the
toolset can capture per-hit combat, damage, and healing data, since that data does **not**
come from the same source as the existing kill/loot/coin pipeline.

## TL;DR

- **The game does not persist combat/damage/healing text to disk.** There is a rich combat
  event model in-game, but it is only rendered live in the chat window — nothing on disk
  contains the damage numbers.
- The existing **Ledger** pipeline (kills, loot, coin, level-ups, party) is the only passive
  on-disk gameplay source. It contains **no combat action codes**.
- Therefore a true DPS/HPS meter requires an *active* capture mechanism (OCR, network, or
  memory) **or** a future dev-side "log chat to file" feature.

## What we looked for

A passive, on-disk source (Option B in the architecture map) that includes damage/heal lines
we could parse as text — e.g. a Unity `Player.log`, an in-game chat transcript, or a
combat-log file.

## What we found

Inspected `%USERPROFILE%\AppData\LocalLow\Niche Worlds Cult\Monsters and Memories\` and the
launcher install dir `%LOCALAPPDATA%\Monsters & Memories\`.

| Source | Contents | Combat data? |
|---|---|---|
| `<server>/<char>/Ledger/*.json` | kills, loot, coin, level-ups, party, trades | No — see action codes below |
| `<server>/<char>/journal/<npc>` | NPC quest dialogue ("X says ...") | No |
| `<server>/<char>/chats.json` | chat **window/channel configuration** + colors | No — config only, not messages |
| `Player.log` / `Player-prev.log` | Unity engine log (Direct3D, physics, LiteNetLib, Addressables) | No |
| `%LOCALAPPDATA%\Monsters & Memories\logs\Monsters & Memories.log` | Tauri **launcher/patcher** log (login, updates) | No (and contains account email — PII) |
| `settings.json` | game settings | No chat-to-file logging toggle |

**Action codes actually present in a daily Social ledger:**

```
act_13  loot            (488)
act_14  corpse / coin   (278)
act_01  level-up        (30)
act_32  party join      (22)
act_34  party leave     (19)
act_35  party leader    (6)
act_33  party disband   (1)
```

No `damage`, `heal`, `hit`, `miss`, `cast`, or `experience-tick` action codes exist.

### Important: the game *does* model combat richly (just not to disk)

`chats.json` enumerates the in-game chat channel taxonomy, which proves the client classifies
every combat event into a category and could, in principle, log them:

```
CombatHitMine, CombatHitVictim, CombatHitPet, CombatHitOther, CombatHitOtherPlayer,
CombatMissMine, CombatMissVictim, ...,
AbilityHitBenefitMine/Victim/Pet/Other..., AbilityHitDetriment..., AbilityMiss..., AbilityResist...,
DamageShieldHitMine/Victim/Other..., BuffTick/Apply/Fade (Benefit|Detriment)...,
DeathMe, DeathMine, DeathOther, Experience, Loot, Coin, Status, Faction, Skill
```

These are displayed in the combat chat window at runtime but are **not written to any file**.

## Options & decision matrix

| Option | Source | Capability | Effort | Fragility | ToS / ban risk | Legal | Viable today? |
|---|---|---|---|---|---|---|---|
| **A. Ledger-only (current)** | on-disk JSON | kills, loot, coin, "who looted what", level-ups (XP proxy) | none (done) | low | none | none | **Yes (shipped)** |
| **B. On-disk combat text log** | (none exists) | full combat/heal text if it existed | low | medium | very low | low | **No — game does not write one** |
| **C. OCR the combat chat window** | screen capture | damage/heal/miss/ability lines as shown | high | high (resolution/theme/scroll) | low | low | Yes, but invasive to set up |
| **D. Network packet capture** | LiteNetLib UDP | true per-hit events if protocol decoded | very high (protocol RE, likely encrypted) | high (patches) | high | gray | Not without major RE |
| **E. Memory reading / injection** | live process | authoritative combat state | very high | very high | highest (anti-cheat/bans) | gray | Not recommended |
| **F. Read-only memory harvest** | `ReadProcessMemory` on `mnm.exe` | formatted combat lines + (future) structured queue | medium | medium (patches) | medium (no injection) | gray | **Yes (shipped)** |

Notes:
- The client uses **LiteNetLib** (seen in `Player.log`) and is **server-authoritative**
  (consistent with `client_re/METADATA-CRYPTO.md`: stats are not shipped in the client).
- Combat data being live-only is a deliberate design point, not an oversight we can patch
  passively.

## Decision

1. **Ship Option A now** — it is already implemented and risk-free. Frame the "combat
   analytics" feature around kills/hr, coin/hr, loot/hr, kill heatmaps, and level/XP-over-time,
   and label clearly that true DPS/HPS is not yet available.
2. **Request a dev-side feature**: ask Niche Worlds Cult to add an optional "log combat/chat
   to file" toggle. This is the clean long-term path — if it lands, Option B becomes a trivial
   text parser (the channel names above are the schema).
3. **Treat Options C/D/E as opt-in, clearly-labeled, separate-risk add-ons** only if there is
   real demand and the user explicitly accepts the risk. **Option F (memory)** is now the
   preferred active capture when `mnm.exe` is running; **Option C (OCR)** remains the fallback
   when the game is closed or capture mode is set to `ocr`.

## Option F — read-only memory harvest (MacroQuest-style)

Reads combat text from `mnm.exe` process memory via `ReadProcessMemory` — **no DLL injection**.
Uses the same line parser as Option C (`mnm_combat_text.py`); events include `"source": "memory"`.

Two sub-modes:

| Mode | Status | How |
|---|---|---|
| **text_scan** | Shipped | Scan readable heap for formatted combat strings |
| **structured** | RE in progress | Read `ChatMessageEntry` queue when offsets in `client_re/mnmlib/combat_struct.json` are filled |

### Setup

```bash
python mnm_client_db.py --fingerprint --resolve-signatures
python mnm_client_db.py --combat-memory-status
python mnm_combat_memory.py --status
python mnm_combat_memory.py --scan-once          # one-shot while in combat
python mnm_combat_memory.py --watch              # append to data/combat-events.json
```

Desktop control panel: **Combat capture mode** = `auto` (memory when game running, else OCR).

RE docs: [`client_re/mnmlib/COMBAT-STRUCT.md`](client_re/mnmlib/COMBAT-STRUCT.md),
type catalog [`client_re/mnmlib/types.json`](client_re/mnmlib/types.json).

After each launcher patch: `python mnm_client_db.py --patch --verify-signatures` — stale
signature caches are archived under `data/client/history/signatures/`.

## Option C prototype (combat window OCR)

The game’s multi-window chat system makes OCR practical when you route combat traffic to the
built-in **`combat`** window (`chats.json` maps 50+ categories there; `windows.json` stores
position/size per character).

### In-game setup (recommended)

1. Right-click the combat chat window → **Combat >** to open filter flyouts. The full menu
   tree (Death, Pet, Melee, Ability, Spell with Apply/Fade/Tick toggles) is cataloged in
   [`data/combat-filter-ui.json`](data/combat-filter-ui.json) — generated from in-game UI
   screenshots. Regenerate with `python mnm_combat_capture.py --export-filters`.
2. **Meter preset** (primary `combat` window): Melee Hits/Misses (Me, Pet, NPCs, Players);
   Ability Hit/Miss; Spell Tick (all Beneficial + Detrimental toggles).
3. **PvP preset** (same window or dedicated): enable **Mine** (hits on you) and **Players**
   under Melee Hits/Misses; Detrimental Me + Players under Spell Apply/Tick; Death → Players.
4. Open chat window filters and ensure **Combat / Ability / Buff / Death** categories route to
   the **combat** window (not the main social chat).
5. Increase font size (`/chatfontsize` or Settings → Chat font size).
6. Use readable colors (e.g. white/yellow damage on dark background).
7. Lock the combat window position; do not collapse it during capture.
8. On ultrawide or multi-monitor setups, **calibrate the screen region** with **Pick on screen…** in the control panel (or `python mnm_combat_capture.py --pick-region`).

#### UI label → channel suffix map

| In-game toggle | chats.json suffix | Example channel |
|---|---|---|
| Me / My | Mine | `CombatHitMine` (you attack) |
| Mine | Victim | `CombatHitVictim` (hit on you) |
| Pet | Pet | `CombatHitPet` |
| NPCs / Others / Co-Players | Other | `CombatHitOther` |
| Players | OtherPlayer | `CombatHitOtherPlayer` |
| Spell Beneficial Me | BenefitMine | `BuffApplyBenefitMine` |
| Spell Detrimental Me | DetrimentVictim | `BuffApplyDetrimentVictim` |

### Tooling

```bash
pip install -r requirements-combat.txt

python mnm_combat_capture.py --layout    # region estimate from windows.json + resolution
python mnm_combat_capture.py --setup     # setup tips
python mnm_combat_capture.py --pick-region   # visual drag-to-select region picker
python mnm_combat_capture.py --region 3260 827 620 293 --once   # test one OCR pass
python mnm_combat_capture.py --watch     # continuous capture → data/combat-events.json
python mnm_combat_capture.py --parse-file data/combat-sample-lines.txt  # parser only
```

Desktop client: **Pick on screen…**, **Start combat OCR**, and **Combat setup…** in [`mnm_client.py`](mnm_client.py).

Modules:
- [`mnm_region_selector.py`](mnm_region_selector.py) — fullscreen drag-to-select screen region picker
- [`mnm_chat_windows.py`](mnm_chat_windows.py) — read `chats.json` / `windows.json`, estimate region
- [`mnm_combat_ocr.py`](mnm_combat_ocr.py) — screen grab + per-line Windows OCR (`OcrResult.lines`) or Tesseract row clustering; scroll-aware `diff_chat_lines` for live capture
- [`mnm_combat_text.py`](mnm_combat_text.py) — EQ-style line parser
- [`mnm_combat_watch.py`](mnm_combat_watch.py) — live loop + `combat-live.json` aggregates

**Limitations:** OCR is approximate (font/theme/resolution dependent). Live capture uses
**one parser event per chat row** (not a whole-window blob). Extend
[`mnm_combat_text.py`](mnm_combat_text.py) patterns as you collect real lines from your combat
window. This does not replace ledger kill/loot tracking — it adds per-hit damage/healing where
the game only shows text on screen.

## If/when we build an OCR or future text-log parser

The parser contract is already known from the channel taxonomy. A combat event normalizes to:

```jsonc
{
  "ts": "2026-06-19T01:23:45",
  "category": "CombatHitMine",      // from the chats.json taxonomy
  "actor": "Freed",                  // attacker / caster / healer
  "target": "a charred acolyte",
  "verb": "slashes",                 // melee verb / ability name
  "amount": 42,                       // damage or heal magnitude
  "kind": "melee|ability|dot|heal|dshield|miss|resist|death",
  "zone": "Ancient Crypt"
}
```

Aggregations to derive: DPS/HPS windows, per-encounter breakdown, ability/spell tables,
incoming vs outgoing, and death recaps — all keyed off `category` + `amount`.
