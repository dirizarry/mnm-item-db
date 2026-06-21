# Data Governance

How submitted data is validated, deduped, trusted, moderated, and versioned. This is the
defense against bad/abusive data poisoning the shared dataset or the wiki.

## Anti-abuse controls

| Control | Where | Default |
|---|---|---|
| Payload size limit | Worker + service | 2 MB (`MAX_BYTES` / `MNM_MAX_BYTES`) |
| Per-install rate limit | Worker (KV) + service (DB) | 30 / hour (`RATE_PER_HOUR` / `MNM_RATE_PER_HOUR`) |
| Schema allow-list | Worker + service | `mnm-ledger-upload/v1`, `v2` only |
| JSON / content-type validation | Worker + service | reject malformed bodies (400/422) |
| Optional ingest token | Worker + service | off (`INGEST_TOKEN` / `MNM_INGEST_TOKEN`) |
| Idempotency | service | duplicate `batch_id` accepted once |

## Anti-poisoning (trust before write-back)

The shared dataset is computed, not blindly summed:

1. **Cross-user dedup** — observations are unioned by hashed dedup tokens, so one event reported
   by many party members (or re-uploaded) counts once (see [PROVENANCE.md](PROVENANCE.md)).
2. **Confidence scoring** — every drop edge gets a noisy-OR confidence from its provenance
   channels and empirical volume; low-confidence edges are visibly flagged.
3. **Independent corroboration for wiki edits** — an edge is only auto-queued for wiki
   write-back when it has `>= MNM_WIKI_MIN_OBSERVATIONS` (default 2) **and**
   `>= MNM_WIKI_MIN_CONTRIBUTORS` (default 2) distinct installs. A single actor cannot push a
   correction to the wiki.
4. **Human gate** — even corroborated candidates only reach the wiki after a moderator approves
   them in the admin UI and a human runs `push_wiki.py`. The wiki is never edited automatically.

Single-contributor or low-confidence claims still appear in `/api/admin/conflicts` for manual
review — they just don't auto-queue.

## Schema & DB versioning / migrations

- **Ingest payload**: versioned in the `schema` field (`mnm-ledger-upload/v1|v2`) plus
  `token_scheme` (`mnm-dedup/v1`). New versions add fields; older clients degrade gracefully
  (the aggregator falls back to raw counts when dedup tokens are absent).
- **Service DB**: `server/db.py` keeps a `schema_version` row and a forward-only `MIGRATIONS`
  list. To evolve the schema, append a migration and bump `SCHEMA_VERSION`; `migrate()` applies
  pending steps idempotently on startup and import.
- **Local artifacts**: `data/game.db` is regenerated from JSON each build (no migration needed);
  the manifest carries `mnm-ledger-manifest/v1`.

## Data retention & deletion

- Raw payloads are stored per `install_id` (R2 object in Phase A, `ingest_payloads` row in
  Phase B) only to recompute aggregates.
- Contributors can delete all their data via the install-id endpoint (see
  [PRIVACY.md](PRIVACY.md)); `forget_install` removes rows and flags the contributor so future
  aggregation excludes them.

## Wiki write-back etiquette

- Respect the wiki's rate limits and the `MnMWikiPush` user agent already set in
  `mnm_wiki.py` / `push_wiki.py`.
- Only push moderator-approved, corroborated corrections; keep the approval trail
  (`wiki_queue.decided_by` / `decided_at`).
