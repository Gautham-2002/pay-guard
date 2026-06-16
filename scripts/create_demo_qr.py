"""
Create Demo QR Code
====================
Generates the test QR code for Scenario 3 (Amazon refund scam).

The QR encodes a UPI deep-link where:
  - pa (payee address) = scammer123@ybl  ← actual scammer UPI
  - pn (payee name)    = Amazon Refund Desk  ← fake display name

This demonstrates the payee name / UPI ID mismatch that Agent 2 detects.

Usage:
    pip install qrcode[pil] pillow
    python scripts/create_demo_qr.py
"""

from __future__ import annotations

from pathlib import Path

try:
    import qrcode
except ImportError:
    print("ERROR: qrcode not installed. Run: pip install qrcode[pil]")
    raise SystemExit(1)

UPI_DEEP_LINK = "upi://pay?pa=scammer123@ybl&pn=Amazon+Refund+Desk&am=9999&cu=INR"
OUTPUT_PATH = Path(__file__).parent.parent / "tests" / "test_qr_refund_scam.png"


def main() -> None:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(UPI_DEEP_LINK)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT_PATH)

    print(f"✅ QR code saved to: {OUTPUT_PATH}")
    print(f"   Encoded: {UPI_DEEP_LINK}")
    print()
    print("This QR encodes:")
    print("  pa (payee) = scammer123@ybl     ← real scammer UPI ID")
    print("  pn (name)  = Amazon Refund Desk ← fake display name")
    print("  am (amount)= 9999               ← ₹9,999")
    print()
    print("Agent 2 will flag: payee name / UPI ID mismatch → refund scam detected.")


if __name__ == "__main__":
    main()
