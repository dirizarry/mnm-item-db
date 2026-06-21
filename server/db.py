"""Shared database layer for the Phase B service.

SQLite reference implementation (swap for Postgres in production by changing the
connection helper — the schema is portable). A tiny `schema_version` table drives
forward-only migrations.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("MNM_SERVER_DB", Path(__file__).parent / "mnm_server.db"))
SCHEMA_VERSION = 1


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row["version"] if row else 0


MIGRATIONS: list[str] = [
    # v1: initial schema
    """
    CREATE TABLE ingest_payloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        install_id TEXT NOT NULL,
        batch_id TEXT NOT NULL UNIQUE,
        schema TEXT NOT NULL,
        received_at REAL NOT NULL,
        share_characters INTEGER DEFAULT 0,
        body TEXT NOT NULL
    );
    CREATE INDEX idx_ingest_install ON ingest_payloads(install_id);

    CREATE TABLE contributors (
        install_id TEXT PRIMARY KEY,
        first_seen REAL NOT NULL,
        last_seen REAL NOT NULL,
        batches INTEGER NOT NULL DEFAULT 0,
        deleted INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE dataset_drops (
        item_title TEXT NOT NULL,
        mob_title TEXT NOT NULL,
        zone TEXT,
        loot_kind TEXT,
        via_mob INTEGER, via_item INTEGER, via_client INTEGER,
        via_ledger INTEGER, via_crowd INTEGER,
        observations INTEGER, contributors INTEGER,
        confidence REAL, status TEXT, conflict INTEGER,
        updated_at REAL NOT NULL,
        PRIMARY KEY (item_title, mob_title, zone)
    );
    CREATE INDEX idx_dataset_status ON dataset_drops(status);

    CREATE TABLE wiki_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_title TEXT NOT NULL,
        mob_title TEXT NOT NULL,
        zone TEXT,
        edit_kind TEXT NOT NULL,
        confidence REAL,
        observations INTEGER,
        reason TEXT,
        state TEXT NOT NULL DEFAULT 'pending',
        created_at REAL NOT NULL,
        decided_at REAL,
        decided_by TEXT,
        UNIQUE (item_title, mob_title, zone, edit_kind)
    );
    CREATE INDEX idx_wiki_state ON wiki_queue(state);
    """,
]


def migrate() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        current = _current_version(conn)
        for version in range(current, SCHEMA_VERSION):
            conn.executescript(MIGRATIONS[version])
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version + 1,))
            conn.commit()
        return _current_version(conn)
    finally:
        conn.close()


# --- ingest ---------------------------------------------------------------------

def record_payload(install_id: str, batch_id: str, schema: str, share: bool, body: dict) -> bool:
    """Persist a payload. Returns False if the batch_id was already seen (idempotent)."""
    now = time.time()
    conn = connect()
    try:
        try:
            conn.execute(
                "INSERT INTO ingest_payloads (install_id, batch_id, schema, received_at, share_characters, body) "
                "VALUES (?,?,?,?,?,?)",
                (install_id, batch_id, schema, now, int(share), json.dumps(body, ensure_ascii=False)),
            )
        except sqlite3.IntegrityError:
            return False
        row = conn.execute("SELECT install_id FROM contributors WHERE install_id=?", (install_id,)).fetchone()
        if row:
            conn.execute("UPDATE contributors SET last_seen=?, batches=batches+1 WHERE install_id=?",
                         (now, install_id))
        else:
            conn.execute("INSERT INTO contributors (install_id, first_seen, last_seen, batches) VALUES (?,?,?,1)",
                         (install_id, now, now))
        conn.commit()
        return True
    finally:
        conn.close()


def recent_payload_count(install_id: str, within_seconds: float) -> int:
    cutoff = time.time() - within_seconds
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) c FROM ingest_payloads WHERE install_id=? AND received_at>=?",
            (install_id, cutoff)).fetchone()
        return row["c"]
    finally:
        conn.close()


def load_payload_bodies(include_deleted: bool = False) -> list[dict]:
    conn = connect()
    try:
        if include_deleted:
            rows = conn.execute("SELECT body FROM ingest_payloads").fetchall()
        else:
            rows = conn.execute(
                "SELECT p.body FROM ingest_payloads p "
                "LEFT JOIN contributors c ON c.install_id=p.install_id "
                "WHERE COALESCE(c.deleted,0)=0").fetchall()
        return [json.loads(r["body"]) for r in rows]
    finally:
        conn.close()


def forget_install(install_id: str) -> int:
    """Right-to-be-forgotten: drop payloads and flag the contributor."""
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM ingest_payloads WHERE install_id=?", (install_id,))
        conn.execute("UPDATE contributors SET deleted=1 WHERE install_id=?", (install_id,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --- dataset --------------------------------------------------------------------

def replace_dataset(drops: list[dict]) -> int:
    now = time.time()
    conn = connect()
    try:
        conn.execute("DELETE FROM dataset_drops")
        conn.executemany(
            "INSERT OR REPLACE INTO dataset_drops "
            "(item_title, mob_title, zone, loot_kind, via_mob, via_item, via_client, via_ledger, via_crowd, "
            " observations, contributors, confidence, status, conflict, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(d["item_title"], d["mob_title"], d.get("zone"), d.get("loot_kind"),
              int(d.get("via_mob", 0)), int(d.get("via_item", 0)), int(d.get("via_client", 0)),
              int(d.get("via_ledger", 0)), int(d.get("via_crowd", 0)),
              int(d.get("observations", 0)), int(d.get("contributors", 0)),
              float(d.get("confidence", 0.0)), d.get("status"), int(d.get("conflict", 0)), now)
             for d in drops],
        )
        conn.commit()
        return len(drops)
    finally:
        conn.close()


def dataset_drops(status: str | None = None, limit: int = 1000, offset: int = 0) -> list[dict]:
    conn = connect()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM dataset_drops WHERE status=? ORDER BY confidence DESC LIMIT ? OFFSET ?",
                (status, limit, offset)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dataset_drops ORDER BY confidence DESC LIMIT ? OFFSET ?",
                (limit, offset)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- wiki queue -----------------------------------------------------------------

def upsert_wiki_candidates(candidates: list[dict]) -> int:
    now = time.time()
    conn = connect()
    added = 0
    try:
        for c in candidates:
            try:
                conn.execute(
                    "INSERT INTO wiki_queue (item_title, mob_title, zone, edit_kind, confidence, observations, reason, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (c["item_title"], c["mob_title"], c.get("zone"), c["edit_kind"],
                     c.get("confidence"), c.get("observations"), c.get("reason"), now),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass  # already queued
        conn.commit()
        return added
    finally:
        conn.close()


def wiki_queue(state: str | None = "pending") -> list[dict]:
    conn = connect()
    try:
        if state:
            rows = conn.execute("SELECT * FROM wiki_queue WHERE state=? ORDER BY confidence DESC", (state,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM wiki_queue ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def decide_wiki(queue_id: int, state: str, by: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE wiki_queue SET state=?, decided_at=?, decided_by=? WHERE id=? AND state='pending'",
            (state, time.time(), by, queue_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def stats() -> dict:
    conn = connect()
    try:
        def one(q):
            return conn.execute(q).fetchone()[0]
        return {
            "payloads": one("SELECT COUNT(*) FROM ingest_payloads"),
            "contributors": one("SELECT COUNT(*) FROM contributors WHERE deleted=0"),
            "drops": one("SELECT COUNT(*) FROM dataset_drops"),
            "confirmed": one("SELECT COUNT(*) FROM dataset_drops WHERE status='confirmed'"),
            "conflicts": one("SELECT COUNT(*) FROM dataset_drops WHERE conflict=1"),
            "wiki_pending": one("SELECT COUNT(*) FROM wiki_queue WHERE state='pending'"),
            "wiki_approved": one("SELECT COUNT(*) FROM wiki_queue WHERE state='approved'"),
        }
    finally:
        conn.close()
