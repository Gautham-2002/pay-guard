"""
PayGuard AI — Agents Package

Sequential pipeline with a pre-flight guardrail coordinated through Band:
  Agent 0 — Input Guardrail             (Featherless AI / Llama 3.3 70B — sync, pre-pipeline)
  Agent 1 — Destination Intelligence   (Featherless AI / Llama 3.3 70B)
  Agent 2 — QR Decode & UPI Validator  (AIML API / GPT-4o vision)
  Agent 3 — Web Intelligence           (Playwright + DDG + Smart Crawler + AIML API)
  Agent 4 — Verdict Synthesis          (AIML API / GPT-4o or Claude 3.5)
"""
