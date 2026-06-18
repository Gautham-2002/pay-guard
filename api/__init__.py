"""
PayGuard AI — API Package

FastAPI application with three route groups:
  /check    — submit a payment destination for analysis (POST + SSE status)
  /report   — retrieve a shareable read-only verdict report
  /history  — user's check history and aggregate fraud-avoided counter
"""
