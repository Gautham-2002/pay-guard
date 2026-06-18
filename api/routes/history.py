"""
Route: /history
===============
GET /history — Transaction history with full aggregate fraud stats.

Returns all previous *completed* checks ordered by most-recent-first, plus:
  - Aggregate counts by verdict (safe / verify / danger)
  - Running total of fraud avoided (sum of amounts for DANGER verdicts)
  - Per-record: amount, product_description, source_type, avoided_fraud_estimate

Implemented in: Phase 6
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.database import get_history_stats, list_check_records

logger = logging.getLogger(__name__)
router = APIRouter()

# Regex to extract numeric value from strings like "₹9,999" or "9999"
_INR_PATTERN = re.compile(r"[\d,]+")


def _parse_inr(value: Optional[str]) -> float:
    """Parse an INR string like '₹9,999' into a float. Returns 0.0 on failure."""
    if not value:
        return 0.0
    # Remove commas and leading currency symbol before matching
    cleaned = str(value).replace(",", "").replace("₹", "").strip()
    match = _INR_PATTERN.search(cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return 0.0
    return 0.0


@router.get(
    "",
    summary="Get transaction history and fraud avoided statistics",
    response_description="List of past checks and aggregate fraud stats",
)
async def get_history(
    limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="Maximum number of records to return",
    ),
) -> JSONResponse:
    """
    Return the most recent completed transaction records and aggregate fraud statistics.

    Each record includes:
    - ``txn_id``                : unique transaction ID
    - ``verdict``               : SAFE | VERIFY | DANGER
    - ``risk_score``            : 0–100
    - ``amount``                : INR amount checked
    - ``product_description``   : what the user said they were paying for
    - ``source_type``           : how the payment destination was received
    - ``band_room_id``          : Band room reference for audit trail
    - ``avoided_fraud_estimate``: INR estimate of fraud avoided (DANGER only)
    - ``created_at``            : ISO-8601 timestamp
    - ``report_url``            : shareable report URL

    Aggregate stats include:
    - ``total_checks``          : total number of completed checks
    - ``safe_count``            : checks with SAFE verdict
    - ``verify_count``          : checks with VERIFY verdict
    - ``danger_count``          : checks with DANGER verdict
    - ``total_fraud_avoided``   : INR string sum of amounts for DANGER verdicts
    """
    # ── Fetch records and stats concurrently ──────────────────────────────────
    try:
        records     = await list_check_records(limit=limit)
        stats       = await get_history_stats()
    except Exception as exc:
        logger.error("GET /history: DB query failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to retrieve history from database."},
        )

    # ── Compute total fraud avoided from per-record amounts ───────────────────
    total_avoided: float = 0.0
    history_rows: list[dict] = []

    for record in records:
        txn_id = record.id

        # Sum avoided fraud for DANGER verdicts using the stored estimate or amount
        if record.verdict == "DANGER":
            # Use the LLM-generated avoided_fraud_estimate if available;
            # fall back to the actual payment amount the user was about to pay.
            avoided_str = record.avoided_fraud_estimate
            if avoided_str:
                total_avoided += _parse_inr(avoided_str)
            elif record.amount:
                total_avoided += record.amount

        history_rows.append({
            "txn_id":                 txn_id,
            "verdict":                record.verdict,
            "risk_score":             record.risk_score,
            "amount":                 record.amount,
            "product_description":    record.product_description,
            "source_type":            record.source_type,
            "band_room_id":           record.band_room_id,
            "avoided_fraud_estimate": record.avoided_fraud_estimate,
            "created_at":             record.created_at,
            "report_url":             f"/api/report/{txn_id}",
        })

    # ── Format total fraud avoided ────────────────────────────────────────────
    fraud_avoided_str: Optional[str] = (
        f"₹{total_avoided:,.0f}" if total_avoided > 0 else None
    )

    return JSONResponse(
        status_code=200,
        content={
            # Aggregate stats
            "total_checks":       stats["total_checks"],
            "safe_count":         stats["safe_count"],
            "verify_count":       stats["verify_count"],
            "danger_count":       stats["danger_count"],
            "total_fraud_avoided": fraud_avoided_str,

            # Transaction records (most recent first, limited by ?limit)
            "transactions": history_rows,
        },
    )
