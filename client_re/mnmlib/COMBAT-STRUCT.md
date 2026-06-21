# Combat message memory layout

Provisional struct catalog for Option F (read-only memory harvest). Offsets are
**patch-specific** — update [`combat_struct.json`](combat_struct.json) after each
`GameAssembly.dll` change (see [`watch_patch.py`](../watch_patch.py)).

## Pipeline (MacroQuest-style)

```
LiteNetLib decode → ChatMessageData / ChatMessageEntry → text formatter → combat UI
                              ↑
                    memory harvest reads here
```

OCR reads the UI tail; structured harvest reads the queue **before** formatting when
offsets are known. Until then, **text_scan** mode scans process heap for formatted
combat strings (still ReadProcessMemory, no injection).

## Types (from metadata string heap)

| Type | Role |
|------|------|
| `ChatLibrary` | Central chat routing / filters |
| `ChatMessageData` | Message payload (text, channel, targets) |
| `ChatMessageEntry` | Queue/history entry |
| `ChatMessageMudView` | Renders EQ-style combat lines |
| `PersistedMessageData` | Saved chat rows |
| `MudChatHandler` | MUD-style message handler |
| `Consider` | Consider/con-level messages |

Full type list: [`types.json`](types.json) (auto-generated from metadata).

## IL2CPP List layout (Unity 6000 x64 baseline)

Typical `List<T>` object (verify in dump.cs):

| Offset | Field |
|--------|-------|
| +0x00 | klass pointer |
| +0x10 | `_items` → array object |
| +0x18 | `_size` int32 |
| +0x1C | `_version` int32 |

Array object:

| Offset | Field |
|--------|-------|
| +0x18 | `max_length` |
| +0x20 | first element (reference types) |

## ChatMessageEntry (TBD — fill from Ghidra)

Expected fields (names from metadata proximity):

- Message text (`System.String`)
- Channel id or enum (maps to `CombatHitMine`, … in [`data/combat-channels.json`](../../data/combat-channels.json))
- Optional target / actor strings

Record offsets in `combat_struct.json` → set `"enabled": true`.

## Text-scan mode (shipped fallback)

When `combat_struct.json` has `"enabled": false`, the harvester:

1. Iterates readable committed regions (`VirtualQueryEx`)
2. Extracts UTF-8 / UTF-16 string candidates
3. Matches combat/heal/death templates (same semantics as [`mnm_combat_text.py`](../../mnm_combat_text.py))
4. Dedupes by normalized line hash

This avoids OCR fragility while structured offsets are unknown.

## Validation workflow

1. Run OCR + memory harvest on a training dummy fight.
2. Compare `combat-events.json` events where `source` is `ocr` vs `memory`.
3. Target ≥95% match on channel + amount + target before enabling structured mode.

### Auto-discovery (runtime structured RE)

While fighting in a busy zone (combat text visible in chat):

```bash
python mnm_combat_memory.py --discover-struct
# or
python mnm_client_db.py --discover-combat-struct
```

On success this writes offsets to `combat_struct.json` with `"enabled": true`.
Restart `--watch` — events will show `"memory_mode": "structured"`.

**MnM-specific:** formatted combat lines live in a **native UTF-8 buffer**, not
`List<ChatMessageEntry>` with `System.String` pointers. Discovery enables
`"layout": "inline_buffer"` when it finds the buffer holder. Re-run discover
after restarting the game (holder addresses change each session).

Failure output includes `diagnostics` (`valid_combat_lines`, `storage_hint`).
When `storage_hint` is `inline_utf8_buffer`, fighting harder will not help if
the buffer holder cannot be located — **text_scan still works** for capture.

If discovery fails entirely, metadata header decrypt + Ghidra is still required
for channel metadata and patch-stable singletons (see below).

Fixtures: [`tests/fixtures/combat_memory/`](../../tests/fixtures/combat_memory/).

## RE checklist (Phase 1 manual)

1. Decrypt metadata header → Il2CppDumper → import `script.json` into Ghidra.
2. Find `ChatLibrary` singleton (`get_Instance` or static field).
3. Trace `ChatMessageEntry` list append on combat hit.
4. Dump one entry in Cheat Engine; fill `combat_struct.json`.
5. Run `python mnm_client_db.py --verify-signatures`.
