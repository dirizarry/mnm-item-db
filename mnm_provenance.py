#!/usr/bin/env python3
"""Provenance, confidence, conflict, and cross-user dedup model.

This module is the single source of truth for *how much we trust a drop link* and
*how to merge observations from many users without double counting*. It is pure
(no IO) so it can be reused by build_relations.py (local) and the crowd aggregator
(server) and unit-tested in isolation.

Provenance channels for a drop edge (item drops from mob in zone):

  via_mob     wiki mob page lists the item as loot
  via_item    wiki item page lists the mob in its `dropsfrom`
  via_client  the item's internal client id (HID) structurally encodes the mob
  via_ledger  the local user empirically looted it (own ledger)
  via_crowd   aggregated empirical observations from other users

See PROVENANCE.md for the full rationale and the dedup rules.
"""

from __future__ import annotations

import hashlib
import math
import re

# Per-channel evidence probability for the noisy-OR confidence model.
# Empirical channels (ledger/crowd) are scored separately by observation volume.
CHANNEL_P = {
    "via_mob": 0.60,
    "via_item": 0.60,
    "via_client": 0.80,
}

# Observation saturation constant: ~observations needed to approach certainty.
OBS_SATURATION = 4.0
# Extra confidence per additional independent contributor (capped).
CONTRIB_BONUS = 0.05
CONTRIB_BONUS_CAP = 0.20

_STOPWORDS = {"a", "an", "the", "of", "and", "ip", "te", "wb", "cmn", "unc", "rare",
              "melee", "caster", "tank", "healer"}


def empirical_probability(observations: int, contributors: int = 1) -> float:
    """Probability an empirically-observed drop is real, given observation volume."""
    if observations <= 0:
        return 0.0
    base = 1.0 - math.exp(-observations / OBS_SATURATION)
    bonus = min(max(contributors - 1, 0) * CONTRIB_BONUS, CONTRIB_BONUS_CAP)
    return min(base + bonus * base, 0.99)


def score_edge(edge: dict) -> dict:
    """Compute confidence (0..1), status, conflict flag, and reasons for an edge.

    `edge` is expected to carry boolean provenance flags plus optional
    `observations` (int) and `contributors` (int).
    """
    channels = []
    for name, p in CHANNEL_P.items():
        if edge.get(name):
            channels.append(p)

    observations = int(edge.get("observations") or 0)
    contributors = int(edge.get("contributors") or 0)
    has_empirical = bool(edge.get("via_ledger") or edge.get("via_crowd"))
    if has_empirical:
        channels.append(empirical_probability(observations, max(contributors, 1)))

    # Noisy-OR over independent evidence channels.
    not_p = 1.0
    for p in channels:
        not_p *= (1.0 - p)
    confidence = round(1.0 - not_p, 4)

    has_wiki = bool(edge.get("via_mob") or edge.get("via_item"))
    has_client = bool(edge.get("via_client"))
    both_wiki = bool(edge.get("via_mob") and edge.get("via_item"))

    reasons: list[str] = []
    if has_empirical and (has_wiki or has_client):
        status = "confirmed"
    elif has_empirical:
        status = "crowd_candidate"  # observed in play, wiki/client doesn't list it
        reasons.append("wiki_missing_observed_drop")
    elif both_wiki or has_client:
        status = "wiki_corroborated"
    elif has_wiki:
        status = "wiki_unconfirmed"
        reasons.append("single_wiki_source_unverified")
    else:
        status = "unknown"

    # A conflict is an actionable disagreement between sources, worth surfacing
    # to the wiki write-back queue or an admin review.
    conflict = status == "crowd_candidate"
    if has_wiki and not has_empirical and confidence < 0.6:
        conflict = True
        reasons.append("low_confidence_wiki_only")

    return {
        "confidence": confidence,
        "status": status,
        "conflict": conflict,
        "conflict_reasons": reasons,
        "observations": observations,
        "contributors": contributors,
    }


# --- client-derived (HID) structural matching -----------------------------------

def _tokens(text: str) -> set[str]:
    parts = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {p for p in parts if len(p) >= 4 and p not in _STOPWORDS and not p.isdigit()}


def client_hid_matches_mob(item_hid: str | None, mob_name: str | None) -> bool:
    """True if the item's internal client id encodes the mob name.

    Example: hid ``ip_te_a_bloodynose_hag_cmn_ears_melee_15`` matched against
    mob ``a bloodynose hag`` shares {bloodynose, hag} -> structurally confirmed.
    """
    if not item_hid or not mob_name:
        return False
    mob_tokens = _tokens(mob_name)
    if not mob_tokens:
        return False
    hid_tokens = _tokens(item_hid.replace("_", " "))
    return bool(mob_tokens & hid_tokens)


# --- cross-user dedup keys -------------------------------------------------------
#
# Two party members independently record the same kill/loot from their own client.
# If both upload, naive summing double-counts. These tokens give a shared identity
# so the server can UNION observations instead of summing them. Tokens are hashed
# so raw character/event identifiers never need to leave the client.

def _hash(*parts: object) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _ts_second(ts: str | None) -> str:
    """Truncate an ISO timestamp to whole seconds (clients agree to ~1s)."""
    if not ts:
        return ""
    return ts[:19]  # YYYY-MM-DDTHH:MM:SS


def kill_token(server: str | None, mob_hid: str | None, corpse_ts: str | None) -> str:
    """Identity of a single mob death, shared across all party members who saw it."""
    return _hash("kill", server, mob_hid, _ts_second(corpse_ts))


def loot_token(server: str | None, item_hid: str | None, mob_hid: str | None,
               ts: str | None, instance_id: str | None = None) -> str:
    """Identity of a single loot drop.

    Unique items carry a globally-unique `instance_id` (the ``<id>|`` prefix the
    ledger puts on the item name) — the strongest dedup key. Fall back to the
    (mob, item, second) tuple for stackable/common drops.
    """
    if instance_id:
        return _hash("loot", server, instance_id)
    return _hash("loot", server, mob_hid, item_hid, _ts_second(ts))


def coin_token(server: str | None, corpse_ts: str | None, looter: str | None) -> str:
    """Identity of a coin award. Coin bulk is tied to a corpse and counted once."""
    return _hash("coin", server, _ts_second(corpse_ts), looter)
