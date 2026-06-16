"""
PayGuard AI — SQLite Persistence Layer
=======================================
Thin async SQLite wrapper for storing transaction verdicts.

Schema (single table):
  transactions:
    txn_id        TEXT PRIMARY KEY
    band_room_id  TEXT NOT NULL
    verdict       TEXT NOT NULL          -- SAFE | VERIFY | DANGER
    risk_score    INTEGER NOT NULL       -- 0–100
    result_json   TEXT NOT NULL          -- full CheckResponse JSON
    created_at    TEXT NOT NULL          -- ISO-8601 UTC

Database location
-----------------
  Default: data/payguard.db  (relative to project root)
  Override via: DB_PATH env var

This is sufficient for a hackathon demo.  Production would use PostgreSQL
or a managed database with proper indexing.

Implemented in: Phase 5
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "payguard.db"
DB_PATH: Path = Path(os.getenv("DB_PATH", str(_DEFAULT_DB_PATH)))

# ─── Schema ───────────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    txn_id       TEXT    PRIMARY KEY,
    band_room_id TEXT    NOT NULL,
    verdict      TEXT    NOT NULL,
    risk_score   INTEGER NOT NULL,
    result_json  TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
);
"""


# ─── Initialisation ───────────────────────────────────────────────────────────


async def init_db() -> None:
    """
    Initialise the SQLite database and create the transactions table if it
    does not already exist.

    Called once on application startup from the FastAPI lifespan hook.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(_CREATE_TABLE_SQL)
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


# ─── Write ────────────────────────────────────────────────────────────────────


async def upsert_transaction(
    txn_id: str,
    band_room_id: str,
    verdict: str,
    risk_score: int,
    result_json: str,
) -> None:
    """
    Insert or replace a transaction record.

    Parameters
    ----------
    txn_id:       Unique transaction identifier.
    band_room_id: Band room UUID for this transaction.
    verdict:      Final verdict string (SAFE | VERIFY | DANGER).
    risk_score:   Integer 0–100.
    result_json:  Full ``CheckResponse`` serialised as JSON.
    """
    from datetime import datetime, timezone

    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO transactions
                (txn_id, band_room_id, verdict, risk_score, result_json, created_at)
            VALUES
                (?, ?, ?, ?, ?, ?)
            """,
            (txn_id, band_room_id, verdict, risk_score, result_json, created_at),
        )
        await db.commit()
    logger.debug("DB: upserted transaction txn_id=%s | verdict=%s", txn_id, verdict)


# ─── Read ─────────────────────────────────────────────────────────────────────


async def get_transaction(txn_id: str) -> Optional[dict]:
    """
    Retrieve a transaction record by ID.

    Parameters
    ----------
    txn_id: Unique transaction identifier.

    Returns
    -------
    A dict with keys: txn_id, band_room_id, verdict, risk_score, result_json,
    created_at — or None if not found.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM transactions WHERE txn_id = ?", (txn_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        return None

    return dict(row)


async def get_transaction_result(txn_id: str) -> Optional[dict]:
    """
    Retrieve and deserialise the full ``CheckResponse`` dict for a transaction.

    Parameters
    ----------
    txn_id: Unique transaction identifier.

    Returns
    -------
    Parsed CheckResponse dict, or None if not found.
    """
    record = await get_transaction(txn_id)
    if record is None:
        return None
    try:
        return json.loads(record["result_json"])
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("DB: failed to parse result_json for txn_id=%s: %s", txn_id, exc)
        return None


async def list_recent_transactions(limit: int = 50) -> list[dict]:
    """
    Return the most recent transactions ordered by creation time (newest first).

    Parameters
    ----------
    limit: Maximum number of rows to return (default 50).

    Returns
    -------
    List of row dicts (without result_json — use get_transaction_result for detail).
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT txn_id, band_room_id, verdict, risk_score, created_at
            FROM transactions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]
