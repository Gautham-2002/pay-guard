"""
PayGuard AI — Database Seeding Script
======================================
Seeds the SQLite database with realistic completed transactions covering all
5 demo scenarios from the PRD, all 3 verdict types, and a variety of Indian
UPI fraud patterns.

Run ONCE (or any time) before demoing:
    uv run python scripts/seed_db.py

What it inserts
---------------
  Scenario 1 — razorpay.com payment gateway fee        → 🟢 SAFE   (score 12)
  Scenario 2 — razorpay-secure.co lookalike domain      → 🔴 DANGER (score 91)
  Scenario 3 — QR refund scam (Amazon refund framing)   → 🔴 DANGER (score 95)
  Scenario 4 — OLX buyer UPI (HITL + VERIFY)            → 🟡 VERIFY (score 52)
  Scenario 5 — Flipkart processing fee scam             → 🔴 DANGER (score 88)
  Bonus 6    — Legitimate Swiggy food order             → 🟢 SAFE   (score 8)
  Bonus 7    — Fake job offer advance fee                → 🔴 DANGER (score 93)
  Bonus 8    — Local kirana QR payment                   → 🟢 SAFE   (score 15)
  Bonus 9    — Instagram seller (social media risk)      → 🟡 VERIFY (score 58)
  Bonus 10   — Fake lottery prize claim                  → 🔴 DANGER (score 97)

The seeded records appear in the History page and can be viewed as reports.
Re-running is idempotent — existing records are skipped by checking txn_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Ensure project root is on sys.path ──────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Seed data ────────────────────────────────────────────────────────────────

def _ts(days_ago: float = 0, hours_ago: float = 0) -> str:
    """Return an ISO-8601 UTC timestamp offset by days/hours."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)
    return dt.isoformat()


SEED_RECORDS = [
    # ── Scenario 1: Legitimate Razorpay ─────────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "scenario-1")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-1")),
        "payment_url": "https://razorpay.com",
        "upi_id": None,
        "amount": 500.0,
        "product_description": "Payment gateway fee",
        "source_type": "website",
        "additional_context": "Paying a fee via the official Razorpay website",
        "verdict": "SAFE",
        "risk_score": 12,
        "plain_english_summary": (
            "Razorpay is India's most established payment gateway, founded in 2014 and regulated by RBI. "
            "The domain is over 10 years old with a clean VirusTotal record and a valid SSL certificate "
            "issued by a trusted CA. All four agents returned low-risk assessments. "
            "A ₹500 payment gateway fee is completely within normal range. This is a safe, legitimate transaction."
        ),
        "recommended_actions": [
            "Proceed with payment — this is a legitimate, verified payment destination.",
            "Keep your payment receipt for records.",
        ],
        "ask_merchant": [],
        "agent1_narrative": (
            "Razorpay.com was registered in 2013 and has a 10+ year track record. VirusTotal shows "
            "zero malicious votes across 70+ scanning engines. The SSL certificate is issued by DigiCert "
            "and is current. The domain's WHOIS data shows consistent registration details matching "
            "Razorpay Financial Services Pvt Ltd. No fraud signals detected at the destination level."
        ),
        "agent2_narrative": (
            "No QR code was uploaded. The user-provided context — paying a gateway fee via a website — "
            "is entirely consistent with Razorpay's actual product offering. No social engineering "
            "patterns detected. No refund framing, no urgency, no UPI ID mismatch. "
            "The ₹500 amount is reasonable for a payment gateway transaction or API subscription fee."
        ),
        "agent3_narrative": (
            "Web intelligence confirms Razorpay's legitimacy: the official site shows corporate registration, "
            "RBI licensing, and established press coverage. DDG searches show no fraud complaints. "
            "Reddit r/india and r/personalfinanceindia discussions about Razorpay are uniformly positive. "
            "Market rate for a payment gateway fee is ₹0–₹5,000 depending on tier, so ₹500 is normal. "
            "No phishing or lookalike sites detected."
        ),
        "price_intelligence": {
            "product_described": "Payment gateway fee",
            "amount_requested": 500.0,
            "market_price_range": "₹0 – ₹5,000 depending on plan",
            "price_anomaly_type": "none",
            "price_narrative": "₹500 is a completely normal amount for a payment gateway fee or subscription.",
        },
        "avoided_fraud_estimate": None,
        "created_at": _ts(days_ago=5, hours_ago=2),
    },

    # ── Scenario 2: Lookalike Domain ─────────────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "scenario-2")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-2")),
        "payment_url": "https://razorpay-secure.co",
        "upi_id": None,
        "amount": 5000.0,
        "product_description": "iPhone 15 Pro",
        "source_type": "whatsapp_unknown",
        "additional_context": "Someone on WhatsApp is selling an iPhone 15 for ₹5,000 and sent this link",
        "verdict": "DANGER",
        "risk_score": 91,
        "plain_english_summary": (
            "This is a sophisticated fraud attempt. The domain 'razorpay-secure.co' is a lookalike designed "
            "to impersonate the legitimate razorpay.com. It was registered only 12 days ago and has 8 "
            "VirusTotal malicious votes. No legitimate seller sends iPhone 15 Pro links over WhatsApp from "
            "unknown numbers. The price of ₹5,000 for an iPhone 15 Pro — which retails for ₹1,10,000+ — "
            "is a classic bait-and-switch scam. DO NOT pay."
        ),
        "recommended_actions": [
            "Do NOT proceed with this payment under any circumstances.",
            "Block the sender on WhatsApp immediately.",
            "Report the UPI ID / link at cybercrime.gov.in or call 1930.",
            "If you have already paid, call your bank's fraud helpline immediately.",
            "Report the domain to Google Safe Browsing: safebrowsing.google.com/safebrowsing/report_phish/",
        ],
        "ask_merchant": [],
        "agent1_narrative": (
            "razorpay-secure.co is a clear impersonation attempt. The legitimate Razorpay domain is "
            "razorpay.com — the '-secure.co' suffix is a well-known phishing pattern. Domain age: 12 days. "
            "VirusTotal: 8 malicious votes, 3 suspicious. Google Safe Browsing flagged as phishing. "
            "The SSL cert was issued just 11 days ago — fraudsters obtain SSL to appear legitimate. "
            "WHOIS registrar is a privacy-shield service, hiding the true owner. HIGH risk."
        ),
        "agent2_narrative": (
            "No QR code uploaded. The context — an unknown WhatsApp contact selling an iPhone 15 Pro — "
            "is a textbook social engineering pattern. 'Unknown WhatsApp seller' is the #1 vector for "
            "Indian e-commerce fraud. There is no legitimate reason for an iPhone seller to send a Razorpay "
            "lookalike link instead of using a real marketplace. The source context alone is HIGH risk."
        ),
        "agent3_narrative": (
            "Playwright crawl of razorpay-secure.co found a generic payment page with Razorpay's logo "
            "stolen and placed on a fake checkout. No GST number, no company registration, no contact details. "
            "DDG search: 'razorpay-secure.co scam' returns 3 Reddit posts from r/india identifying this as "
            "a phishing site. Price intelligence: iPhone 15 Pro market price is ₹1,09,900 – ₹1,39,900. "
            "Selling for ₹5,000 is a 95% discount — impossible legitimately. Classic bait-and-switch: "
            "take payment, never deliver goods."
        ),
        "price_intelligence": {
            "product_described": "iPhone 15 Pro",
            "amount_requested": 5000.0,
            "market_price_range": "₹1,09,900 – ₹1,39,900",
            "price_anomaly_type": "too_low_bait",
            "price_narrative": (
                "₹5,000 for an iPhone 15 Pro is a 95% discount from market price. "
                "This is a classic bait listing — the phone will never be delivered. "
                "No legitimate seller can offer this price."
            ),
        },
        "avoided_fraud_estimate": "₹5,000",
        "created_at": _ts(days_ago=4, hours_ago=6),
    },

    # ── Scenario 3: QR Refund Scam ───────────────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "scenario-3")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-3")),
        "payment_url": None,
        "upi_id": "scammer123@ybl",
        "amount": 9999.0,
        "product_description": "Amazon refund",
        "source_type": "whatsapp_unknown",
        "additional_context": "They said scan this QR to get an Amazon refund — QR has pa=scammer123@ybl",
        "verdict": "DANGER",
        "risk_score": 95,
        "plain_english_summary": (
            "This is the QR refund scam — one of India's most common UPI frauds. You CANNOT receive money "
            "by scanning a QR code. QR codes only SEND money. 'scammer123@ybl' is a personal account "
            "with no connection to Amazon. The pre-filled amount of ₹9,999 is deliberately chosen to stay "
            "just under UPI daily limits and bank alert thresholds. If you scan this, ₹9,999 will be "
            "instantly debited from your account. DO NOT SCAN."
        ),
        "recommended_actions": [
            "DO NOT scan this QR code — you will SEND money, not receive it.",
            "Block and report the WhatsApp number immediately.",
            "Contact Amazon's official customer care at amazon.in to verify any real refund.",
            "Amazon refunds are NEVER processed via QR code — they go directly to your original payment method.",
            "Report to cybercrime.gov.in or call 1930.",
        ],
        "ask_merchant": [],
        "agent1_narrative": (
            "UPI ID: scammer123@ybl. The username 'scammer123' is a random individual handle — not a "
            "merchant account. Amazon uses registered business UPI IDs, not personal @ybl accounts. "
            "The @ybl PSP (Yes Bank UPI) is commonly used in scam UPI IDs. No domain to analyse since "
            "this is UPI-only. The name-account mismatch is a critical signal: UPI payee name 'Amazon "
            "Refund Desk' with address 'scammer123@ybl' has zero legitimate connection."
        ),
        "agent2_narrative": (
            "CRITICAL: This is a textbook QR refund scam. The QR encodes pa=scammer123@ybl, "
            "pn='Amazon Refund Desk', am=9999. The payee name 'Amazon Refund Desk' is completely "
            "fabricated — anyone can set any pn value in a UPI QR. The actual recipient is scammer123@ybl. "
            "The refund framing is the definitive fraud signal: you CANNOT receive money by scanning a QR. "
            "QR codes only initiate OUTGOING payments. Amount ₹9,999 is a classic just-under-₹10,000 limit "
            "to avoid bank transaction alerts. ALL signals point to HIGH fraud."
        ),
        "agent3_narrative": (
            "DDG search 'scammer123@ybl fraud' returned 2 posts on r/india warning about this specific UPI ID. "
            "Search 'Amazon India refund process': Amazon's official help confirms refunds go to original "
            "payment source — never via QR code. Price intelligence: 'Amazon refund' has no market price "
            "range — this context makes no sense for a payment (you don't pay to receive a refund). "
            "The entire framing is designed to confuse. Web intelligence confirms: HIGH risk, scam confirmed."
        ),
        "price_intelligence": {
            "product_described": "Amazon refund",
            "amount_requested": 9999.0,
            "market_price_range": None,
            "price_anomaly_type": "type_mismatch",
            "price_narrative": (
                "You never pay to receive a refund. Being asked to pay ₹9,999 to 'receive' an Amazon "
                "refund is logically impossible — this is pure fraud framing. Additionally, ₹9,999 is "
                "a classic scam amount chosen to stay just under ₹10,000 alert thresholds."
            ),
        },
        "avoided_fraud_estimate": "₹9,999",
        "created_at": _ts(days_ago=3, hours_ago=14),
    },

    # ── Scenario 4: OLX Buyer — VERIFY + HITL ────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "scenario-4")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-4")),
        "payment_url": None,
        "upi_id": "merchant@ybl",
        "amount": 1200.0,
        "product_description": "Used laptop",
        "source_type": "olx_marketplace",
        "additional_context": "OLX buyer wants to buy my used laptop and sent this UPI ID to pay me",
        "verdict": "VERIFY",
        "risk_score": 52,
        "plain_english_summary": (
            "This transaction has mixed signals that require verification. The UPI ID 'merchant@ybl' is "
            "a personal individual account — not a business. ₹1,200 for a used laptop is suspiciously low "
            "and could indicate the buyer intends to defraud you (OLX buyer scam: they send collect requests "
            "instead of payments). However, the amount is low enough that the risk is manageable if you take "
            "the right precautions. Verify the buyer's identity before proceeding."
        ),
        "recommended_actions": [
            "Never enter your UPI PIN to 'accept' payment — that sends money FROM you, not to you.",
            "Ask the buyer to show you a payment confirmation screenshot BEFORE releasing the laptop.",
            "Only accept payment via direct bank transfer, not UPI collect requests.",
            "Meet the buyer in person at a public place; insist on cash or confirmed bank transfer.",
            "Reverse image-search the buyer's profile photo to check for fake identity.",
        ],
        "ask_merchant": [
            "Can you share your government ID (Aadhaar card) before we meet?",
            "Why are you offering ₹1,200 for a laptop? What is your budget?",
            "Are you willing to pay via bank transfer instead of UPI?",
            "Can we meet at a public place like a mall or bank branch for the exchange?",
        ],
        "agent1_narrative": (
            "UPI ID: merchant@ybl. The prefix 'merchant' is misleading — this is a personal @ybl account, "
            "not a registered merchant account. Legitimate marketplace transactions should use the buyer's "
            "bank app's native payment feature, not a manually shared UPI ID. The @ybl suffix is fine "
            "(Yes Bank UPI), but the account structure suggests an individual, not a verified merchant. "
            "Risk is MEDIUM — not definitively fraudulent, but requires caution."
        ),
        "agent2_narrative": (
            "No QR code uploaded. OLX buyer scenario: the risk pattern here is the OLX Buyer Scam — "
            "where the 'buyer' sends a UPI collect request (which asks you to PAY them), not a payment. "
            "The user's phrasing 'sent this UPI ID to pay me' suggests they understand they are the seller, "
            "which is correct. However, entering your UPI PIN for any incoming request from this buyer "
            "would send money TO them. HITL question was triggered to confirm the user's role in this transaction."
        ),
        "agent3_narrative": (
            "DDG search 'merchant@ybl OLX scam' — no specific results for this UPI ID. "
            "Reddit r/india posts on OLX laptop scams: common pattern is buyer sends fake payment screenshot. "
            "Price check: used laptop prices in India range ₹8,000–₹40,000 depending on specs. "
            "₹1,200 is suspiciously below market rate — could indicate a bait offer to get you to share "
            "your UPI details. VERIFY verdict recommended: low amount makes risk manageable, "
            "but identity verification of buyer is strongly advised."
        ),
        "price_intelligence": {
            "product_described": "Used laptop",
            "amount_requested": 1200.0,
            "market_price_range": "₹8,000 – ₹40,000 (depending on brand and specs)",
            "price_anomaly_type": "too_low_bait",
            "price_narrative": (
                "₹1,200 is significantly below market rate for any functional laptop. "
                "While possible for a broken or parts-only device, buyers offering very low prices "
                "on OLX are sometimes testing if you will engage — and then attempting payment fraud."
            ),
        },
        "avoided_fraud_estimate": None,
        "created_at": _ts(days_ago=2, hours_ago=8),
    },

    # ── Scenario 5: Flipkart Processing Fee Scam ─────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "scenario-5")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-5")),
        "payment_url": "https://flipkart.com",
        "upi_id": None,
        "amount": 15000.0,
        "product_description": "Processing fee to release order",
        "source_type": "email",
        "additional_context": "Email from flipkart-help.com asking to pay ₹15,000 as processing fee to release my order",
        "verdict": "DANGER",
        "risk_score": 88,
        "plain_english_summary": (
            "This is a fake customer support / processing fee scam. Flipkart NEVER charges processing fees "
            "to release orders. The email came from 'flipkart-help.com' — a fake domain, not flipkart.com. "
            "₹15,000 for 'processing' a delivery is a classic advance fee fraud targeting Flipkart customers. "
            "The destination flipkart.com is legitimate, but that is irrelevant — the payment being requested "
            "is not going to Flipkart; it is being extracted by fraudsters impersonating their support team."
        ),
        "recommended_actions": [
            "Do NOT pay ₹15,000 or any amount as a 'processing fee' — Flipkart does not charge these.",
            "Contact Flipkart's official support ONLY via flipkart.com/helpcentre or 1800-202-9898.",
            "Forward the fake email to support@flipkart.com as a fraud report.",
            "Report the sender at cybercrime.gov.in.",
            "Check your Flipkart order status directly at flipkart.com — it will not show any pending fee.",
        ],
        "ask_merchant": [],
        "agent1_narrative": (
            "The URL flipkart.com is legitimate — old domain, clean VirusTotal record. However, the user's "
            "context reveals the key fraud signal: the email came from flipkart-help.com, NOT flipkart.com. "
            "flipkart-help.com is a fraudulent domain registered to impersonate Flipkart customer support. "
            "The legitimate domain is irrelevant here — the scam is operating from the lookalike email domain. "
            "This is a fake customer support operation using Flipkart's brand."
        ),
        "agent2_narrative": (
            "No QR code. The fraud pattern is 'fake customer support + processing fee'. "
            "Flipkart, Amazon, and other e-commerce companies NEVER request money to process or release orders. "
            "The email domain 'flipkart-help.com' is the definitive fraud indicator — legitimate Flipkart "
            "emails come only from @flipkart.com. ₹15,000 for courier processing is also a known scam "
            "amount for fake customs/shipping fees. This is a HIGH confidence fraud case."
        ),
        "agent3_narrative": (
            "Web search confirms: 'flipkart-help.com' is not affiliated with Flipkart. "
            "Flipkart's official domain is only flipkart.com. Reddit r/india: multiple posts warning about "
            "fake Flipkart support emails asking for 'processing fees' of ₹5,000–₹20,000. "
            "Price intelligence: there is no legitimate product purchase here — the ₹15,000 is entirely a "
            "fraudulent extraction. Official Flipkart help page confirms: no processing fees are ever charged "
            "for order delivery. Evidence is unambiguous: DANGER."
        ),
        "price_intelligence": {
            "product_described": "Processing fee to release order",
            "amount_requested": 15000.0,
            "market_price_range": "₹0 (no legitimate processing fee exists for Flipkart orders)",
            "price_anomaly_type": "type_mismatch",
            "price_narrative": (
                "E-commerce platforms like Flipkart never charge processing fees to release orders. "
                "₹15,000 for 'processing' is entirely fabricated. The amount is designed to feel "
                "significant enough to be 'real' but not so large as to immediately trigger disbelief."
            ),
        },
        "avoided_fraud_estimate": "₹15,000",
        "created_at": _ts(days_ago=1, hours_ago=20),
    },

    # ── Bonus 6: Swiggy food order (SAFE) ────────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "bonus-6")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-6")),
        "payment_url": "https://swiggy.com",
        "upi_id": None,
        "amount": 385.0,
        "product_description": "Food delivery — biryani and raita",
        "source_type": "website",
        "additional_context": "Ordering food via the Swiggy app checkout",
        "verdict": "SAFE",
        "risk_score": 8,
        "plain_english_summary": (
            "Swiggy is a legitimate, RBI-compliant Indian food delivery platform. The domain is 8+ years old "
            "with a perfect VirusTotal record. ₹385 is entirely reasonable for a food order. "
            "All agent signals are clean. Proceed with payment."
        ),
        "recommended_actions": [
            "Safe to proceed — this is a verified, legitimate payment destination.",
        ],
        "ask_merchant": [],
        "agent1_narrative": "Swiggy.com is registered since 2014, clean VirusTotal, valid DigiCert SSL. Zero fraud signals.",
        "agent2_narrative": "No QR code. Food delivery via official app — completely normal use case. No social engineering.",
        "agent3_narrative": "Swiggy is India's second-largest food delivery platform. ₹385 is within normal range for 1-2 dishes + delivery.",
        "price_intelligence": {
            "product_described": "Food delivery",
            "amount_requested": 385.0,
            "market_price_range": "₹100 – ₹800 typical for 1-2 dish delivery",
            "price_anomaly_type": "none",
            "price_narrative": "₹385 is completely normal for a restaurant food order with delivery charges.",
        },
        "avoided_fraud_estimate": None,
        "created_at": _ts(days_ago=1, hours_ago=5),
    },

    # ── Bonus 7: Fake job offer advance fee (DANGER) ─────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "bonus-7")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-7")),
        "payment_url": None,
        "upi_id": "hr.global.jobs@paytm",
        "amount": 2500.0,
        "product_description": "Registration fee for remote data entry job",
        "source_type": "whatsapp_unknown",
        "additional_context": "WhatsApp message: selected for ₹40,000/month job, pay ₹2,500 registration fee to activate kit",
        "verdict": "DANGER",
        "risk_score": 93,
        "plain_english_summary": (
            "This is an advance fee / fake job scam. No legitimate employer charges a 'registration fee' "
            "to give you a job. The pattern — WhatsApp job offer, high salary (₹40,000/month), pay first "
            "to 'activate work kit' — is textbook advance fee fraud. The UPI ID 'hr.global.jobs@paytm' "
            "is a personal account with a business-sounding name designed to appear official. "
            "Pay nothing. Report this number immediately."
        ),
        "recommended_actions": [
            "Do NOT pay any registration, kit, or processing fee — legitimate jobs never require upfront payment.",
            "Block the WhatsApp number immediately.",
            "Report the UPI ID at cybercrime.gov.in or call 1930.",
            "Verify job offers only through official company websites or established platforms like LinkedIn, Naukri.",
        ],
        "ask_merchant": [],
        "agent1_narrative": (
            "UPI ID: hr.global.jobs@paytm. The name 'hr.global.jobs' is a personal account mimicking "
            "a corporate HR department. This naming pattern (company-sounding prefix + PSP) is extremely "
            "common in job scam UPI IDs. No WHOIS to analyse (UPI-only). HIGH risk from VPA structure alone."
        ),
        "agent2_narrative": (
            "Advance fee scam detected. The pattern: WhatsApp job offer → high salary promise → upfront fee "
            "to 'activate' something → no job delivered. This is classified as 'advance fee fraud' in India's "
            "cybercrime taxonomy. ₹2,500 is calibrated to be small enough to seem non-threatening but large "
            "enough to be worth collecting at scale. The fraudster contacts thousands of job seekers."
        ),
        "agent3_narrative": (
            "Reddit r/india search 'data entry job WhatsApp advance fee' returns dozens of victim reports. "
            "This exact pattern (₹40,000/month promise, pay ₹2,000–₹5,000 first) is well-documented. "
            "Price intelligence: paying ₹2,500 to GET a job is impossible in legitimate employment. "
            "The 'salary' of ₹40,000/month is used as bait — the fraudster makes money from registration "
            "fees alone, never intending to provide any work."
        ),
        "price_intelligence": {
            "product_described": "Job registration fee",
            "amount_requested": 2500.0,
            "market_price_range": "₹0 (no legitimate job requires an upfront fee)",
            "price_anomaly_type": "advance_fee",
            "price_narrative": (
                "Legitimate employers never charge registration fees. ₹2,500 framed as a 'kit activation' "
                "fee is the advance fee component of this scam. At scale, collecting ₹2,500 from "
                "even 100 victims yields ₹2.5 lakh — a profitable scam with near-zero cost."
            ),
        },
        "avoided_fraud_estimate": "₹2,500",
        "created_at": _ts(hours_ago=18),
    },

    # ── Bonus 8: Local kirana QR (SAFE) ──────────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "bonus-8")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-8")),
        "payment_url": None,
        "upi_id": "ram.kirana.store@oksbi",
        "amount": 234.0,
        "product_description": "Grocery purchase at local store",
        "source_type": "in_person",
        "additional_context": "Scanning QR code at my regular kirana store for grocery bill",
        "verdict": "SAFE",
        "risk_score": 15,
        "plain_english_summary": (
            "This looks like a routine in-person grocery payment. The UPI ID 'ram.kirana.store@oksbi' "
            "follows a merchant-style naming pattern on SBI's UPI infrastructure. ₹234 is a completely "
            "normal grocery bill amount. In-person payments at physical stores you visit regularly "
            "are extremely low risk. Safe to proceed."
        ),
        "recommended_actions": [
            "Safe to proceed — routine in-person merchant payment.",
            "Verify the payee name shown in your UPI app matches the store name before confirming.",
        ],
        "ask_merchant": [],
        "agent1_narrative": "UPI ID ram.kirana.store@oksbi on SBI's network. Name suggests local merchant. Amount ₹234 is normal grocery bill.",
        "agent2_narrative": "In-person at a regular store. No social engineering, no refund framing, no urgency. Low risk context.",
        "agent3_narrative": "No web search needed for routine in-person grocery payment. Amount is within normal range.",
        "price_intelligence": None,
        "avoided_fraud_estimate": None,
        "created_at": _ts(hours_ago=10),
    },

    # ── Bonus 9: Instagram seller (VERIFY) ───────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "bonus-9")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-9")),
        "payment_url": None,
        "upi_id": "fashionhub2024@ybl",
        "amount": 1800.0,
        "product_description": "Designer kurti from Instagram seller",
        "source_type": "social_media",
        "additional_context": "Found this seller on Instagram, placed order via DM, they want payment before shipping",
        "verdict": "VERIFY",
        "risk_score": 58,
        "plain_english_summary": (
            "Instagram sellers carry significant fraud risk but are not always fraudulent. "
            "'fashionhub2024@ybl' is an individual account — not a registered business. "
            "The pattern — Instagram DM order, payment before shipping — is how many small legitimate "
            "Indian sellers operate, BUT is also the exact same pattern used by scammers. "
            "₹1,800 is within range for a kurti. Verify the seller's track record before paying."
        ),
        "recommended_actions": [
            "Request Cash on Delivery (COD) if available — preferred option.",
            "If prepaid: pay only after reviewing verified customer reviews with photos.",
            "Ask for the seller's Instagram handle age — check 'About this account' for join date.",
            "Never pay 100% upfront for first purchase from an unknown Instagram seller.",
            "Use UPI with purchase protection where possible (e.g., Flipkart, Meesho for kurti purchases).",
        ],
        "ask_merchant": [
            "Can you share 5+ recent customer reviews with photos of delivered items?",
            "Is Cash on Delivery available for my pincode?",
            "What is your return/refund policy if the item doesn't match the photo?",
            "Can you provide your business GST number or Instagram profile age?",
        ],
        "agent1_narrative": (
            "UPI ID fashionhub2024@ybl — personal individual account. The '2024' suffix is common for "
            "quickly-created accounts. @ybl is Yes Bank UPI. No business registration detectable. "
            "Risk is MEDIUM — could be a legitimate home-based seller or a scammer."
        ),
        "agent2_narrative": (
            "Social media seller + pre-payment = elevated risk pattern. Instagram commerce is a real "
            "phenomenon in India, but is also a major vector for non-delivery fraud. Without the ability "
            "to verify seller identity, the risk cannot be definitively resolved. VERIFY recommended."
        ),
        "agent3_narrative": (
            "DDG search 'fashionhub2024 instagram scam' — no specific results. "
            "Reddit r/india has general warnings about Instagram fashion sellers. "
            "Price check: designer kurtis range ₹500–₹5,000 on legitimate platforms; ₹1,800 is reasonable. "
            "VERIFY verdict: amount is manageable, but seller verification is strongly recommended."
        ),
        "price_intelligence": {
            "product_described": "Designer kurti",
            "amount_requested": 1800.0,
            "market_price_range": "₹500 – ₹5,000 depending on brand and fabric",
            "price_anomaly_type": "none",
            "price_narrative": "₹1,800 is within the normal range for a designer kurti from a boutique seller.",
        },
        "avoided_fraud_estimate": None,
        "created_at": _ts(hours_ago=3),
    },

    # ── Bonus 10: Fake lottery (DANGER) ──────────────────────────────────────
    {
        "txn_id": "demo-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "bonus-10")),
        "band_room_id": "band-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, "band-10")),
        "payment_url": "https://kbc-lottery-winner.in",
        "upi_id": None,
        "amount": 5000.0,
        "product_description": "Tax payment to claim KBC lottery prize of ₹25 lakh",
        "source_type": "sms",
        "additional_context": "SMS says I won KBC lottery ₹25 lakh. Pay ₹5,000 tax to release prize.",
        "verdict": "DANGER",
        "risk_score": 97,
        "plain_english_summary": (
            "This is a KBC/lottery advance fee scam — one of India's oldest and most recognisable frauds. "
            "There is no KBC lottery. You did not win ₹25 lakh. Kaun Banega Crorepati selects contestants "
            "through official applications at sonyliv.com — never via SMS or random prize announcements. "
            "The domain 'kbc-lottery-winner.in' was registered 4 days ago specifically to run this scam. "
            "The ₹5,000 'tax' is the advance fee — once paid, they will demand more. Pay nothing."
        ),
        "recommended_actions": [
            "Pay NOTHING. This is a well-documented advance fee scam.",
            "Delete the SMS and block the sender number.",
            "Report to cybercrime.gov.in and the National Cyber Crime Reporting Portal.",
            "KBC's official site is sonyliv.com — verify all KBC communications there.",
            "Warn family members, especially elderly relatives who may be targeted.",
        ],
        "ask_merchant": [],
        "agent1_narrative": (
            "kbc-lottery-winner.in registered 4 days ago. VirusTotal: 11 malicious votes. "
            "Google Safe Browsing: flagged as deceptive site. SSL certificate is Let's Encrypt "
            "(free, obtained same day as domain registration — standard scam setup). "
            "The domain name itself ('kbc-lottery-winner') is designed to trigger confirmation bias "
            "in recipients who want to believe they won. HIGHEST risk."
        ),
        "agent2_narrative": (
            "Lottery advance fee scam. Pattern: unsolicited SMS → prize notification → pay 'tax'/'fee' → "
            "prize never delivered, more fees demanded until victim stops paying. "
            "The KBC brand is specifically chosen because of its association with life-changing prize money. "
            "Paying ₹5,000 is the entry point — victims who pay are then targeted for ₹10,000, ₹25,000 "
            "until they either run out of money or realise the scam."
        ),
        "agent3_narrative": (
            "Playwright crawl: site shows fake KBC branding, countdown timer, 'winner certificate'. "
            "No official Sony/KBC branding elements match the legitimate show. "
            "DDG: 'kbc-lottery-winner.in scam' — 4 results including a cybercrime advisory. "
            "Reddit r/india: this exact SMS text pattern reported multiple times in the last month. "
            "KBC official: Sony confirms KBC never contacts winners via SMS or charges fees. "
            "Price: paying ₹5,000 'tax' to claim ₹25 lakh is the classic 1–2% advance fee ratio "
            "designed to seem plausible. This is a 100% fraud scenario."
        ),
        "price_intelligence": {
            "product_described": "KBC lottery prize tax payment",
            "amount_requested": 5000.0,
            "market_price_range": "₹0 (legitimate lottery winnings never require upfront tax payment)",
            "price_anomaly_type": "advance_fee",
            "price_narrative": (
                "In India, TDS on lottery winnings is deducted at source by the organiser — "
                "winners never pay tax upfront to claim prizes. Any request to pay ₹5,000 "
                "(or any amount) before receiving a prize is definitively fraudulent."
            ),
        },
        "avoided_fraud_estimate": "₹5,000",
        "created_at": _ts(hours_ago=1),
    },
]


# ─── Database insertion ───────────────────────────────────────────────────────


async def seed() -> None:
    """Insert all seed records into the database, skipping existing ones."""
    # Bootstrap SQLAlchemy ORM tables
    from api.database import init_db, _get_session_factory, CheckRecord
    from sqlalchemy import select

    await init_db()
    logger.info("Database initialised")

    factory = _get_session_factory()
    inserted = 0
    skipped = 0

    async with factory() as session:
        for rec in SEED_RECORDS:
            # Check if this txn_id already exists
            existing = await session.get(CheckRecord, rec["txn_id"])
            if existing is not None:
                logger.info("SKIP  txn_id=%s (already exists)", rec["txn_id"])
                skipped += 1
                continue

            # Build the full CheckResponse JSON for fast report retrieval
            result_dict = {
                "txn_id": rec["txn_id"],
                "band_room_id": rec["band_room_id"],
                "verdict": rec["verdict"],
                "risk_score": rec["risk_score"],
                "plain_english_summary": rec["plain_english_summary"],
                "recommended_actions": rec["recommended_actions"],
                "ask_merchant": rec["ask_merchant"],
                "agent_narratives": {
                    "destination_intelligence": rec["agent1_narrative"],
                    "qr_upi_validator": rec["agent2_narrative"],
                    "web_intelligence": rec["agent3_narrative"],
                    "verdict_synthesis": rec["plain_english_summary"],
                },
                "price_intelligence": rec["price_intelligence"],
                "avoided_fraud_estimate": rec.get("avoided_fraud_estimate"),
                "report_url": f"/api/report/{rec['txn_id']}",
            }

            db_record = CheckRecord(
                id=rec["txn_id"],
                band_room_id=rec["band_room_id"],
                payment_url=rec.get("payment_url"),
                upi_id=rec.get("upi_id"),
                amount=rec["amount"],
                product_description=rec.get("product_description"),
                source_type=rec["source_type"],
                additional_context=rec.get("additional_context"),
                verdict=rec["verdict"],
                risk_score=rec["risk_score"],
                plain_english_summary=rec["plain_english_summary"],
                recommended_actions=rec["recommended_actions"],
                ask_merchant=rec["ask_merchant"],
                agent1_narrative=rec["agent1_narrative"],
                agent2_narrative=rec["agent2_narrative"],
                agent3_narrative=rec["agent3_narrative"],
                price_intelligence=rec.get("price_intelligence"),
                avoided_fraud_estimate=rec.get("avoided_fraud_estimate"),
                result_json=json.dumps(result_dict, ensure_ascii=False),
                status="complete",
                hitl_question=None,
                created_at=rec["created_at"],
                updated_at=rec["created_at"],
            )
            session.add(db_record)
            inserted += 1
            logger.info(
                "INSERT txn_id=%s | verdict=%s | %-50s",
                rec["txn_id"],
                rec["verdict"],
                (rec.get("product_description") or rec.get("payment_url") or rec.get("upi_id") or "")[:50],
            )

        await session.commit()

    logger.info("")
    logger.info("─" * 60)
    logger.info("Seeding complete: %d inserted, %d skipped", inserted, skipped)
    logger.info("─" * 60)
    logger.info("")
    logger.info("Verdict breakdown:")
    verdicts = [r["verdict"] for r in SEED_RECORDS]
    logger.info("  🟢 SAFE   : %d", verdicts.count("SAFE"))
    logger.info("  🟡 VERIFY : %d", verdicts.count("VERIFY"))
    logger.info("  🔴 DANGER : %d", verdicts.count("DANGER"))
    logger.info("")
    logger.info("Run the server and open /history to see seeded data.")


if __name__ == "__main__":
    asyncio.run(seed())
