"""
Route: /history
===============
GET /history — User's check history with aggregate "fraud avoided" counter.

Returns all previous checks and a running total of fraud amounts avoided
when DANGER verdicts were raised.

Implemented in: Phase 5
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# TODO (Phase 5): Implement GET / — query SQLite DB for all transactions,
#                 compute aggregate avoided_fraud_estimate sum.
