"""
PayGuard AI — Pydantic Request / Response Models
=================================================
All data contracts used across agents, routes, and the Band room.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


# ─── Enumerations ─────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    """How the user received the payment destination."""

    whatsapp_unknown = "whatsapp_unknown"
    whatsapp_known = "whatsapp_known"
    website = "website"
    sms = "sms"
    email = "email"
    in_person = "in_person"
    olx_marketplace = "olx_marketplace"
    social_media = "social_media"
    other = "other"


class VerdictLevel(str, Enum):
    """Final three-tier verdict emitted by Agent 4."""

    SAFE = "SAFE"
    VERIFY = "VERIFY"
    DANGER = "DANGER"


class RiskLevel(str, Enum):
    """Intermediate risk signal used by Agents 1–3."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ─── Request Models ───────────────────────────────────────────────────────────


class CheckRequest(BaseModel):
    """
    Payload submitted by the user to initiate a fraud check.

    Note: qr_image is handled as `UploadFile` directly in the route handler
    (multipart/form-data), not here.
    """

    payment_url: Optional[str] = Field(
        default=None,
        description="Full URL to analyse (e.g. https://flipkart-sale.in/pay)",
        examples=["https://razorpay.com"],
    )
    upi_id: Optional[str] = Field(
        default=None,
        description="UPI Virtual Payment Address (e.g. merchant@paytm)",
        examples=["merchant@paytm"],
    )
    amount: float = Field(
        ...,
        gt=0,
        description="INR amount the user is about to pay",
        examples=[9999.0],
    )
    product_description: Optional[str] = Field(
        default=None,
        description="What the user says they are paying for",
        examples=["iPhone 15 Pro 256GB"],
    )
    source_type: SourceType = Field(
        ...,
        description="How the payment destination was received",
    )
    additional_context: Optional[str] = Field(
        default="",
        description="Free-text notes from the user",
        examples=["They said scan to get refund"],
    )


# ─── Agent Output Models ──────────────────────────────────────────────────────


class PriceIntelligence(BaseModel):
    """Price anomaly analysis produced by Agent 3, Step 5."""

    product_described: str
    amount_requested: float
    market_price_range: Optional[str] = None
    price_anomaly_type: Optional[str] = Field(
        default=None,
        description=(
            "too_low_bait | too_high | advance_fee | "
            "round_limit | type_mismatch | none"
        ),
    )
    price_narrative: str


class Agent1Output(BaseModel):
    """
    Published to Band room by Agent 1 — Destination Intelligence.
    Power: Featherless AI (Llama 3.3 70B)
    """

    agent: str = "destination_intelligence"
    sequence: int = 1
    destination_type: str = Field(
        ..., description="UPI_ID | URL | BOTH"
    )
    upi_id: Optional[str] = None
    upi_psp: Optional[str] = None
    risk_level: RiskLevel
    top_signals: List[str] = Field(
        ..., description="Key raw evidence findings"
    )
    agent_narrative: str = Field(
        ..., description="3–4 sentence LLM reasoning over all signals"
    )
    raw_evidence: dict = Field(
        default_factory=dict,
        description="Unprocessed data from WHOIS/VT/SSL/GSB APIs",
    )
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str


class Agent2Output(BaseModel):
    """
    Published to Band room by Agent 2 — QR Decode & UPI Validator.
    Power: AIML API (GPT-4o vision)
    """

    agent: str = "qr_upi_validator"
    sequence: int = 2
    decoded_upi_id: Optional[str] = None
    payee_name_from_qr: Optional[str] = None
    prefilled_amount: Optional[float] = None
    upi_context_mismatch: bool = False
    refund_scam_indicator: bool = False
    visual_context: Optional[str] = None
    social_engineering_pattern: Optional[str] = None
    manipulation_signals: List[str] = []
    agent_narrative: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str


class Agent3Output(BaseModel):
    """
    Published to Band room by Agent 3 — Web Intelligence.
    Power: Playwright + DDG + PRAW + BeautifulSoup + AIML API synthesis
    """

    agent: str = "web_intelligence"
    sequence: int = 3
    website_crawled: bool = False
    screenshot_analysis: Optional[str] = None
    page_fraud_signals: List[str] = []
    fraud_complaints_found: bool = False
    complaint_sources: List[str] = []
    official_alternative_found: bool = False
    official_site: Optional[str] = None
    reddit_mentions: List[str] = []
    price_intelligence: Optional[PriceIntelligence] = None
    web_risk_level: RiskLevel
    agent_narrative: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str


class Agent4Output(BaseModel):
    """
    Published to Band room by Agent 4 — Verdict Synthesis.
    Power: AIML API (GPT-4o or Claude 3.5 Sonnet)

    Verdict scoring:
      SAFE   → risk_score 0–30
      VERIFY → risk_score 31–65
      DANGER → risk_score 66–100
    """

    agent: str = "verdict_synthesis"
    sequence: int = 4
    verdict: VerdictLevel
    risk_score: int = Field(..., ge=0, le=100)
    plain_english_summary: str
    recommended_actions: List[str]
    ask_merchant: List[str] = []
    agent_agreement: str = Field(
        ..., description="ALL_AGREE | PARTIAL_CONFLICT | FULL_CONFLICT"
    )
    conflict_resolution: Optional[str] = None
    avoided_fraud_estimate: Optional[str] = None
    band_room_id: str
    timestamp: str


# ─── HITL Models ──────────────────────────────────────────────────────────────


class HITLMessage(BaseModel):
    """
    Human-in-the-Loop message posted to the Band room by the user.
    The next agent reads this exactly as it reads any other agent's output.
    """

    type: str = "human_response"
    question_from_agent: str
    human_answer: str
    timestamp: str


# ─── API Response Models ───────────────────────────────────────────────────────


class CheckResponse(BaseModel):
    """Final response returned to the frontend after all 4 agents complete."""

    txn_id: str
    band_room_id: str
    verdict: VerdictLevel
    risk_score: int
    plain_english_summary: str
    recommended_actions: List[str]
    ask_merchant: List[str]
    agent_narratives: dict = Field(
        ..., description="Map of agent_name → agent_narrative string"
    )
    price_intelligence: Optional[PriceIntelligence] = None
    report_url: str = Field(
        ..., description="Shareable read-only report URL: /report/{txn_id}"
    )


class CheckStatus(BaseModel):
    """
    Real-time pipeline status polled or streamed via SSE.

    status values:
      agent_1_running | agent_2_running | agent_3_running |
      hitl_waiting    | agent_4_running | complete
    """

    txn_id: str
    status: str
    current_agent: Optional[str] = None
    hitl_question: Optional[str] = None
    result: Optional[CheckResponse] = None
