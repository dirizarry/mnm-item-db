# Provenance, Confidence, Conflict & Cross-User Dedup

How the toolset decides *how much to trust a drop link* and *how to merge many users'
observations without double counting*. Implemented in [`mnm_provenance.py`](mnm_provenance.py),
consumed by [`build_relations.py`](build_relations.py) (local) and
[`mnm_crowd_aggregate.py`](mnm_crowd_aggregate.py) (crowd).

## Provenance channels

Every drop edge (item drops from mob in zone) records which independent sources attest to it:

| Flag | Source | Strength |
|---|---|---|
| `via_mob` | wiki mob page lists the item as loot | medium (unverified) |
| `via_item` | wiki item page lists the mob in `dropsfrom` | medium (unverified) |
| `via_client` | the item's internal client id (HID) structurally encodes the mob | high (structural) |
| `via_ledger` | the local user empirically looted it | high (empirical) |
| `via_crowd` | aggregated empirical observations from other users | high (empirical, scales) |

`via_client` is derived by `client_hid_matches_mob()`: e.g. the HID
`ip_te_a_bloodynose_hag_cmn_ears_melee_15` shares the tokens `{bloodynose, hag}` with the mob
`a bloodynose hag`, so the game's own item id confirms the source.

## Confidence model

`score_edge()` combines channels with a **noisy-OR**: each channel has an independent
probability of being correct, and `confidence = 1 - prod(1 - p_channel)`.

- Structural channels: `via_mob`/`via_item` = 0.60 each, `via_client` = 0.80.
- Empirical channels (`via_ledger`/`via_crowd`) contribute
  `p = 1 - exp(-observations / 4)`, saturating toward certainty as observations accumulate,
  plus a small bonus per additional independent contributor (capped at +0.20).

So a single unverified wiki claim is ~0.60; both wiki sides agreeing is ~0.84; one empirical
observation alone is ~0.22 but climbs past 0.90 by ~9 observations; combining wiki + empirical
+ client approaches 0.99.

## Status & conflict

`score_edge()` also assigns a `status` and a boolean `conflict`:

| status | meaning |
|---|---|
| `confirmed` | empirically observed **and** attested by wiki/client |
| `crowd_candidate` | observed in play but wiki/client doesn't list it -> **wiki gap to fix** |
| `wiki_corroborated` | both wiki sides agree, or client-encoded, but never observed |
| `wiki_unconfirmed` | a single wiki source, unverified |
| `unknown` | no recognized source |

`conflict = true` for `crowd_candidate` edges (the wiki is missing a real drop) and for
low-confidence (`< 0.6`) wiki-only edges. These feed the wiki write-back queue and the admin
conflict-resolution view.

## Cross-user dedup rules

The ledger already **partitions events by actor**: a user only records loot they personally
looted (`looter == self`) and kills they personally got the corpse for. So summing counts
across users is *mostly* correct — but re-uploads, overlapping `Ledger/Archive` snapshots, and
multi-character witnessing can still double count. We defend against this with **hashed
per-observation dedup tokens** that give the same physical event a stable identity across
clients, so the aggregator **unions** rather than sums.

Tokens (20-char sha256 prefixes — raw character/event ids never leave the client):

| Event | Token key | Rule |
|---|---|---|
| Kill | `kill \| server \| mob_hid \| ts(second)` | one death = one token, regardless of who reports it |
| Loot | `loot \| server \| instance_id` (unique items) else `loot \| server \| mob_hid \| item_hid \| ts(second)` | unique items have a globally-unique instance id = strongest key |
| Coin | `coin \| server \| corpse_ts(second) \| looter` | coin bulk is tied to a corpse and counted once |

The aggregator computes:

- **distinct observations** of a drop = `len(union(loot_tokens))` across all payloads
- **distinct kills** of a mob (the drop-rate denominator) = `len(union(kill_tokens))`
- **contributors** = number of distinct `install_id`s that reported the edge

`drop_rate(item, mob) = distinct_loot_observations / distinct_kills`, both deduped.

### Schema

The upload payload is `mnm-ledger-upload/v2` (`token_scheme: mnm-dedup/v1`). v2 adds
`dedup_tokens` to each `loot_confirmations` row and each `top_mobs` row. Clients that predate
v2 (no tokens) degrade gracefully: the aggregator falls back to summing raw counts for those
rows only.

## Pipeline

```
client uploads (v2)  ->  data/crowd-inbox/*.json
        |
        v
python mnm_crowd_aggregate.py   -> data/crowd-drops.json, data/crowd-kills.json
        |
        v
python build_relations.py       -> game.db drops table with
                                    via_client/via_crowd, observations, contributors,
                                    confidence, status, conflict
        |
        v
python build_site.py            -> site drop index carries conf + status per link
```
