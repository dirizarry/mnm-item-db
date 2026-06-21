"""Server-side aggregation + trust engine (Phase B).

Runs the same dedup + provenance logic as the offline tools, but over all stored
upload payloads, to produce:
  - the public dataset (scored drop edges) -> dataset_drops
  - moderated wiki write-back candidates    -> wiki_queue

Reuses the offline modules so local and server scoring stay identical.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mnm_crowd_aggregate import aggregate as aggregate_payloads  # noqa: E402
from build_relations import build_drops, load_and_normalize, ITEMS_PATH, MOBS_PATH  # noqa: E402

from . import db


# Anti-poisoning: a single actor should not be able to push edits to the wiki.
# Require independent corroboration before auto-queuing. Single-contributor edges
# still surface in /api/admin/conflicts for manual moderator review.
MIN_OBSERVATIONS = int(os.environ.get("MNM_WIKI_MIN_OBSERVATIONS", "2"))
MIN_CONTRIBUTORS = int(os.environ.get("MNM_WIKI_MIN_CONTRIBUTORS", "2"))


def _wiki_candidates(drops: list[dict]) -> list[dict]:
    """Turn actionable edges into moderated wiki write-back candidates."""
    out = []
    for d in drops:
        status = d.get("status")
        if (status == "crowd_candidate"
                and d.get("observations", 0) >= MIN_OBSERVATIONS
                and d.get("contributors", 0) >= MIN_CONTRIBUTORS):
            out.append({
                "item_title": d["item_title"],
                "mob_title": d["mob_title"],
                "zone": d.get("zone"),
                "edit_kind": "add_drop",  # wiki is missing an empirically-observed drop
                "confidence": d.get("confidence"),
                "observations": d.get("observations"),
                "reason": "Observed in play by the community but not listed on the wiki.",
            })
    return out


def run_aggregation() -> dict:
    """Recompute the public dataset from all stored payloads. Returns a summary."""
    payloads = db.load_payload_bodies()
    crowd_drops, crowd_kills = aggregate_payloads(payloads)

    items, mobs = [], []
    if ITEMS_PATH.is_file() and MOBS_PATH.is_file():
        items, mobs = load_and_normalize(ITEMS_PATH, MOBS_PATH)

    # Wiki (items/mobs) + crowd observations -> scored edges (no local ledger on server).
    drops = build_drops(items, mobs, ledger_drops=None, crowd_drops=crowd_drops)

    db.replace_dataset(drops)
    candidates = _wiki_candidates(drops)
    queued = db.upsert_wiki_candidates(candidates)

    return {
        "payloads": len(payloads),
        "crowd_drops": len(crowd_drops),
        "dataset_drops": len(drops),
        "confirmed": sum(1 for d in drops if d.get("status") == "confirmed"),
        "crowd_candidates": sum(1 for d in drops if d.get("status") == "crowd_candidate"),
        "wiki_candidates_new": queued,
    }
