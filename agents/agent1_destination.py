"""
Agent 1 — Destination Intelligence Agent
=========================================
Power:   Featherless AI — meta-llama/Llama-3.3-70B-Instruct
Trigger: Always runs first in the pipeline.

Responsibilities
----------------
Collects raw signals about the payment destination (URL or UPI ID) using
external intelligence APIs, then passes the evidence to the Featherless LLM
for holistic reasoning. Does NOT make rule-based decisions — reasoning is
entirely delegated to the LLM.

Data collected
--------------
- WHOIS     : domain age, registrar, country of registration
- VirusTotal: malicious/suspicious votes from 70+ security engines
- Google Safe Browsing: phishing/malware classification flag
- SSL cert  : validity, issuance date, issuing Certificate Authority
- UPI VPA   : parse `username@psp`, assess PSP suffix legitimacy

LLM reasoning prompts
---------------------
- Are any signals individually minor but collectively alarming?
- Does the UPI handle pattern suggest an individual vs merchant account?
- What would a sophisticated fraudster do to appear legitimate here?
- Are there inconsistencies between what appears legitimate and the data?

Band output schema
------------------
See api/models.py :: Agent1Output

Implemented in: Phase 1
"""

from __future__ import annotations

# TODO (Phase 1): Implement run() — collect domain intel, call Featherless LLM,
#                 publish Agent1Output to Band room.


async def run(
    txn_id: str,
    band_room_id: str,
    payment_url: str | None,
    upi_id: str | None,
    amount: float,
    product_description: str | None,
    source_type: str,
    additional_context: str,
) -> dict:
    """
    Entry point for Agent 1.

    Parameters
    ----------
    txn_id:              Unique transaction ID for this check session.
    band_room_id:        Band room identifier to publish results into.
    payment_url:         URL to analyse (may be None if only UPI ID given).
    upi_id:              UPI Virtual Payment Address (may be None if only URL given).
    amount:              INR amount the user is about to pay.
    product_description: What the user says they are paying for (optional).
    source_type:         How the payment detail was received (SourceType enum value).
    additional_context:  Free-text notes from the user.

    Returns
    -------
    Agent1Output-compatible dict published to the Band room.
    """
    raise NotImplementedError("Agent 1 is implemented in Phase 1")
