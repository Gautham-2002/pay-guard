"""
PayGuard AI — SQLAlchemy Async Database Layer
=============================================
Full ORM-backed persistence using SQLAlchemy 2.x async engine + aiosqlite.

Schema
------
Single table ``checks`` stores every transaction from submission to completion,
including all agent narratives, price intelligence, and verdict details.

Design decisions
----------------
- Uses SQLAlchemy 2.x declarative ORM for type-safety and schema evolution.
- ``get_db()`` is an async generator dependency for FastAPI ``Depends()``.
- ``init_db()`` creates tables on startup (idempotent — uses CREATE IF NOT EXISTS).
- JSON columns serialised natively by SQLAlchemy's ``JSON`` type on SQLite.
- Timestamps stored as ISO-8601 strings for portability.

Implemented in: Phase 6
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, List, Optional

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    select,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "payguard.db"
DB_PATH: Path = Path(os.getenv("DB_PATH", str(_DEFAULT_DB_PATH)))

DATABASE_URL: str = f"sqlite+aiosqlite:///{DB_PATH}"

# ─── SQLAlchemy engine + session factory ──────────────────────────────────────

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_engine() -> AsyncEngine:
    """Return (or lazily create) the singleton async engine."""
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,           # set True for SQL debug logging
            future=True,
            connect_args={"check_same_thread": False},
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (or lazily create) the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


# ─── ORM Base ─────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ─── ORM Model ────────────────────────────────────────────────────────────────


class CheckRecord(Base):
    """
    Persisted record of a single PayGuard AI fraud check.

    Status lifecycle
    ----------------
    pending → running → agent_1_running → agent_2_running →
    agent_3_running → [hitl_waiting] → agent_4_running →
    complete | error
    """

    __tablename__ = "checks"

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(String, primary_key=True)   # txn_id (UUID)
    band_room_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ── Input payload ─────────────────────────────────────────────────────────
    payment_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    upi_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    product_description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)

    # ── Final verdict (populated after Agent 4) ───────────────────────────────
    verdict: Mapped[Optional[str]] = mapped_column(String, nullable=True)          # SAFE | VERIFY | DANGER
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)      # 0–100
    plain_english_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommended_actions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ask_merchant: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # ── Per-agent narratives (populated progressively) ────────────────────────
    agent1_narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent2_narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent3_narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Price intelligence (from Agent 3, if product_description provided) ────
    price_intelligence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── Fraud avoidance estimate (from Agent 4, for DANGER verdicts) ──────────
    avoided_fraud_estimate: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ── Status tracking ───────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="pending",
    )
    hitl_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Full result JSON (denormalised for fast report retrieval) ─────────────
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


# ─── Startup / teardown ───────────────────────────────────────────────────────


async def init_db() -> None:
    """
    Create all tables if they do not already exist.

    Safe to call multiple times (idempotent). Invoked from the FastAPI
    lifespan hook on application startup.
    """
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("api.database: tables created/verified at %s", DB_PATH)


async def close_db() -> None:
    """Dispose the async engine. Call on application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("api.database: engine disposed")


# ─── FastAPI dependency ───────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a scoped ``AsyncSession``.

    Usage::

        @router.post("/check")
        async def check(db: AsyncSession = Depends(get_db)):
            ...
    """
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── Write helpers ────────────────────────────────────────────────────────────


async def create_check_record(
    txn_id: str,
    amount: float,
    source_type: str,
    payment_url: Optional[str] = None,
    upi_id: Optional[str] = None,
    product_description: Optional[str] = None,
    band_room_id: Optional[str] = None,
    status: str = "running",
) -> None:
    """
    Insert a new CheckRecord at the start of the pipeline.

    Parameters
    ----------
    txn_id:              Unique transaction ID (UUID).
    amount:              INR amount the user intends to pay.
    source_type:         How the payment destination was received.
    payment_url:         URL being checked (optional).
    upi_id:              UPI VPA being checked (optional).
    product_description: What the user claims to be paying for (optional).
    band_room_id:        Band room UUID (may be None initially).
    status:              Initial pipeline status (default ``"running"``).
    """
    factory = _get_session_factory()
    async with factory() as session:
        record = CheckRecord(
            id=txn_id,
            band_room_id=band_room_id,
            payment_url=payment_url,
            upi_id=upi_id,
            amount=amount,
            product_description=product_description,
            source_type=source_type,
            status=status,
        )
        session.add(record)
        await session.commit()
    logger.debug("api.database: created CheckRecord txn_id=%s status=%s", txn_id, status)


async def update_check_status(
    txn_id: str,
    status: str,
    band_room_id: Optional[str] = None,
    hitl_question: Optional[str] = None,
) -> None:
    """
    Update the status (and optionally band_room_id / hitl_question) of a check.

    Parameters
    ----------
    txn_id:        Transaction ID to update.
    status:        New pipeline status string.
    band_room_id:  Band room UUID (set once created).
    hitl_question: Pending HITL question text (only when status=hitl_waiting).
    """
    factory = _get_session_factory()
    async with factory() as session:
        record = await session.get(CheckRecord, txn_id)
        if record is None:
            logger.warning("api.database: update_check_status — txn_id=%s not found", txn_id)
            return
        record.status = status
        record.updated_at = datetime.now(timezone.utc).isoformat()
        if band_room_id is not None:
            record.band_room_id = band_room_id
        if hitl_question is not None:
            record.hitl_question = hitl_question
        elif status != "hitl_waiting":
            record.hitl_question = None  # Clear HITL question when no longer waiting
        await session.commit()
    logger.debug("api.database: updated status txn_id=%s → %s", txn_id, status)


async def complete_check_record(
    txn_id: str,
    verdict: str,
    risk_score: int,
    plain_english_summary: str,
    recommended_actions: List[str],
    ask_merchant: List[str],
    agent1_narrative: Optional[str],
    agent2_narrative: Optional[str],
    agent3_narrative: Optional[str],
    price_intelligence: Optional[dict],
    avoided_fraud_estimate: Optional[str],
    result_json: str,
) -> None:
    """
    Finalise a CheckRecord with the full verdict + all agent outputs.

    Called by the pipeline orchestrator after Agent 4 completes.

    Parameters
    ----------
    txn_id:                 Transaction ID.
    verdict:                Final verdict (SAFE | VERIFY | DANGER).
    risk_score:             0–100 risk score.
    plain_english_summary:  Plain-language verdict summary.
    recommended_actions:    List of recommended action strings.
    ask_merchant:           List of merchant verification questions.
    agent1_narrative:       Agent 1 narrative string.
    agent2_narrative:       Agent 2 narrative string.
    agent3_narrative:       Agent 3 narrative string.
    price_intelligence:     Price anomaly dict from Agent 3 (or None).
    avoided_fraud_estimate: INR string e.g. '₹9,999' (or None).
    result_json:            Full serialised CheckResponse JSON.
    """
    factory = _get_session_factory()
    async with factory() as session:
        record = await session.get(CheckRecord, txn_id)
        if record is None:
            logger.warning("api.database: complete_check_record — txn_id=%s not found", txn_id)
            return
        record.verdict = verdict
        record.risk_score = risk_score
        record.plain_english_summary = plain_english_summary
        record.recommended_actions = recommended_actions
        record.ask_merchant = ask_merchant
        record.agent1_narrative = agent1_narrative
        record.agent2_narrative = agent2_narrative
        record.agent3_narrative = agent3_narrative
        record.price_intelligence = price_intelligence
        record.avoided_fraud_estimate = avoided_fraud_estimate
        record.result_json = result_json
        record.status = "complete"
        record.hitl_question = None
        record.updated_at = datetime.now(timezone.utc).isoformat()
        await session.commit()
    logger.info("api.database: completed CheckRecord txn_id=%s verdict=%s", txn_id, verdict)


async def mark_check_error(txn_id: str, error_message: str) -> None:
    """
    Mark a CheckRecord as errored.

    Parameters
    ----------
    txn_id:        Transaction ID.
    error_message: Error description for audit purposes.
    """
    factory = _get_session_factory()
    async with factory() as session:
        record = await session.get(CheckRecord, txn_id)
        if record is None:
            return
        record.status = "error"
        record.plain_english_summary = f"Pipeline error: {error_message[:500]}"
        record.updated_at = datetime.now(timezone.utc).isoformat()
        await session.commit()
    logger.debug("api.database: marked error txn_id=%s", txn_id)


# ─── Read helpers ─────────────────────────────────────────────────────────────


async def get_check_record(txn_id: str) -> Optional[CheckRecord]:
    """
    Retrieve a single CheckRecord by transaction ID.

    Parameters
    ----------
    txn_id: Transaction ID.

    Returns
    -------
    CheckRecord ORM object, or None if not found.
    """
    factory = _get_session_factory()
    async with factory() as session:
        return await session.get(CheckRecord, txn_id)


async def list_check_records(limit: int = 50) -> List[CheckRecord]:
    """
    Return the most recent CheckRecords (newest first), limited to ``limit``.

    Only returns completed checks (status='complete') to avoid cluttering
    the history with in-flight transactions.

    Parameters
    ----------
    limit: Maximum records to return (1–200).

    Returns
    -------
    List of CheckRecord ORM objects.
    """
    factory = _get_session_factory()
    async with factory() as session:
        stmt = (
            select(CheckRecord)
            .where(CheckRecord.status == "complete")
            .order_by(CheckRecord.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_history_stats() -> dict:
    """
    Return aggregate stats across all completed transactions.

    Returns
    -------
    dict with keys:
      - total_checks (int)
      - safe_count (int)
      - verify_count (int)
      - danger_count (int)
    """
    factory = _get_session_factory()
    async with factory() as session:
        stmt = (
            select(
                func.count(CheckRecord.id).label("total"),
                func.sum(
                    func.cast(CheckRecord.verdict == "SAFE", Integer)
                ).label("safe"),
                func.sum(
                    func.cast(CheckRecord.verdict == "VERIFY", Integer)
                ).label("verify"),
                func.sum(
                    func.cast(CheckRecord.verdict == "DANGER", Integer)
                ).label("danger"),
            ).where(CheckRecord.status == "complete")
        )
        row = (await session.execute(stmt)).one()
    return {
        "total_checks": row.total or 0,
        "safe_count": row.safe or 0,
        "verify_count": row.verify or 0,
        "danger_count": row.danger or 0,
    }
