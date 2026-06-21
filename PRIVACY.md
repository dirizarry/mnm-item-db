# Privacy

This tool runs on your machine and reads your own Monsters & Memories logs. Nothing is sent
anywhere unless you explicitly submit it. This document states exactly what is collected and
what leaves your computer.

## Local-only by default

Mining, the live watcher, the dashboard, and gear planning are **entirely local** — they read
your `LocalLow` logs and write to your workspace. No network calls. Submitting data is a
separate, explicit action ("Submit data" button / `--upload`).

## What a submission contains

When you submit, the client builds an **aggregated** `mnm-ledger-upload/v2` payload. It contains
*counts and rates*, never your raw chat, tells, or message contents:

| Field | Contents | Personal? |
|---|---|---|
| `install_id` | a stable hash of your logs folder path | pseudonymous (not your name) |
| `batch_id` | random per-submission id | no |
| `summary` / `manifest.stats` | totals (events, kills, coin) | no |
| `heatmap` | kills per zone/day/**server** | **character name removed unless you opt in** |
| `drop_rates`, `loot_confirmations` | item/mob/zone + observed counts + dedup tokens | no |
| `top_mobs`, `vendor_prices` | mob/item aggregates | no |
| `levelups_by_day` | level transitions per day/zone | character included **only if you opt in** |
| `characters`, `servers` | your character/server names | **only if you opt in** |
| `hardcore_profiles` | Magnificent standings (name, level, zone, kills, status) | **only if you opt in to character names and Magnificent sharing** |

`dedup_tokens` are 20-char SHA-256 prefixes of event identities — they let the server avoid
double-counting shared party loot without revealing names or raw ids.

## Character-name sharing is opt-in

Character names are **off by default**. They are included only when you tick
"Share character names" (or set `MNM_UPLOAD_SHARE_CHARACTERS=1`). With sharing off:
- no `characters`/`servers` blocks,
- `character` is stripped from heatmap cells and level-ups,
- you remain a pseudonymous `install_id`.

## Magnificent standings sharing is opt-in

Magnificent (hardcore) leaderboard entries are **off by default**. They are included only when
you enable **Share character names** and **Share Magnificent standings** (or set
`MNM_UPLOAD_SHARE_CHARACTERS=1` and `MNM_UPLOAD_SHARE_HARDCORE=1`). Profiles contain your
character name, server, level, zone, kill count, and Magnificent status — never raw journal
dialogue.

## Screenshot submissions (Magnificent Hall)

You can join the public Magnificent Hall **without running local tools** by uploading a
character-select screenshot on the [Magnificent Hall submit page](site/hardcore/submit.html).
OCR runs in your browser; you confirm name, level, zone, and that the **Hardcore** tag was
detected before submitting.

Screenshot submissions include:

| Field | Notes |
| --- | --- |
| Character name, server, level, zone, race/class | Parsed from your screenshot (you can correct before submit) |
| `proof.hardcore_detected` | Whether OCR saw the Hardcore tag |
| `proof.ocr_text` | Truncated OCR text for moderation (not displayed publicly) |
| `proof.image_sha256` | Hash of the image file (image itself is not uploaded unless you choose a future feature) |
| `submit_id` / `install_id` | Pseudonymous browser ids stored in localStorage |

Party grouping in game does **not** count as proof of Hardcore status. Only your own
screenshot or your opt-in log upload can add you to the board.

## Opt-out and deletion (right to be forgotten)

- Don't want to contribute? Simply never set a submit URL — the tool stays fully local.
- Already submitted and want it gone? Your `install_id` is the only handle the server has.
  Delete everything tied to it:

```
curl -X DELETE https://<service>/api/data/install/<your-install-id>
```

This removes your stored payloads and excludes them from future aggregation
(`server/db.py::forget_install`). Your `install_id` is printed in the upload payload and in
`data/ledger-manifest.json`.

## What is never collected

Tells/whispers, chat messages, account email, passwords, IP-based identity, or anything from
outside the game's Ledger analytics. The launcher log (which *does* contain your account email)
is never read or transmitted by this tool.

See [GOVERNANCE.md](GOVERNANCE.md) for how submitted data is validated and moderated.
