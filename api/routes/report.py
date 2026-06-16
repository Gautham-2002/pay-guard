"""
Route: /report
==============
GET /report/{txn_id} — Shareable, read-only verdict report page.

Returns the full Agent4Output verdict plus all three agent narratives.
Can be shared with police complaints or cybercrime.gov.in.

Implemented in: Phase 5
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# TODO (Phase 5): Implement GET /{txn_id} — fetch transaction from DB,
#                 return CheckResponse with all agent narratives.
