# Phase 6 — FastAPI Backend: Full API Server

## Context
Phases 0–5 are complete. All 4 agents work and publish to Band. The HITL manager is built.
PRD: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

This phase builds the complete FastAPI backend — all routes, database, SSE streaming, and orchestration logic.

---

## Task 1: Database setup (SQLite via SQLAlchemy async)

Create `api/database.py`:

```python
# Tables needed:

class CheckRecord(Base):
    __tablename__ = "checks"
    id = Column(String, primary_key=True)           # txn_id (UUID)
    band_room_id = Column(String)
    payment_url = Column(String, nullable=True)
    upi_id = Column(String, nullable=True)
    amount = Column(Float)
    product_description = Column(String, nullable=True)
    source_type = Column(String)
    verdict = Column(String)                         # SAFE | VERIFY | DANGER
    risk_score = Column(Integer)
    plain_english_summary = Column(Text)
    recommended_actions = Column(JSON)
    ask_merchant = Column(JSON)
    agent1_narrative = Column(Text, nullable=True)
    agent2_narrative = Column(Text, nullable=True)
    agent3_narrative = Column(Text, nullable=True)
    price_intelligence = Column(JSON, nullable=True)
    avoided_fraud_estimate = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")       # pending | running | hitl_waiting | complete | error
    hitl_question = Column(String, nullable=True)
```

Create `api/database.py` with `get_db()` async context manager. Auto-create tables on startup.

---

## Task 2: Build api/routes/check.py — Main Analysis Endpoint

### POST /check (multipart/form-data)

```python
@router.post("/check")
async def check_payment(
    payment_url: str = Form(None),
    upi_id: str = Form(None),
    amount: float = Form(...),
    product_description: str = Form(None),
    source_type: str = Form(...),
    additional_context: str = Form(""),
    qr_image: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
) -> CheckResponse:
```

Validation:
- At least one of `payment_url`, `upi_id`, or `qr_image` must be provided
- `amount` must be > 0
- `source_type` must be a valid SourceType enum value

Orchestration:
```python
txn_id = str(uuid.uuid4())

# 1. Create Band room
band_room = await band_client.create_room(name=f"txn-{txn_id}")

# 2. Save initial record to DB (status=running)
await db.save_check(txn_id, payload, band_room.id, status="running")

# 3. Read QR image bytes if provided
qr_bytes = await qr_image.read() if qr_image else None

# 4. Sequential agent pipeline
agent1 = await agent1_module.run(band_room, url=payment_url, upi_id=upi_id, ...)
await update_status(txn_id, "agent_2_running", db)

agent2 = await agent2_module.run(band_room, qr_image_bytes=qr_bytes, ...)
await update_status(txn_id, "agent_3_running", db)

# 5. Check for HITL after Agent 2
if agent2.needs_clarification:
    await update_status(txn_id, "hitl_waiting", db, hitl_question=agent2.clarification_question)
    # Return immediately with hitl_waiting status — frontend polls /check/{txn_id}/status
    return CheckStatus(txn_id=txn_id, status="hitl_waiting", hitl_question=agent2.clarification_question)

agent3 = await agent3_module.run(band_room, url=payment_url, ...)
await update_status(txn_id, "agent_4_running", db)

# 6. Check for HITL after Agent 3
if agent3.needs_clarification:
    await update_status(txn_id, "hitl_waiting", db, hitl_question=agent3.clarification_question)
    return CheckStatus(txn_id=txn_id, status="hitl_waiting", hitl_question=agent3.clarification_question)

agent4 = await agent4_module.run(band_room, payload)

# 7. Save complete result to DB
await db.save_complete(txn_id, agent1, agent2, agent3, agent4)

# 8. Return verdict
return CheckResponse(
    txn_id=txn_id,
    band_room_id=band_room.id,
    verdict=agent4.verdict,
    risk_score=agent4.risk_score,
    ...
    report_url=f"/report/{txn_id}"
)
```

### POST /check/{txn_id}/respond — HITL Response

```python
@router.post("/check/{txn_id}/respond")
async def submit_hitl_response(
    txn_id: str,
    answer: str = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    User has answered the HITL question.
    1. Load the check record from DB (verify status=hitl_waiting)
    2. Get the Band room
    3. Publish human_response to Band room via hitl_manager
    4. Resume the pipeline from where it left off (Agent 3 or Agent 4)
    5. Return the final verdict
    """
```

### GET /check/{txn_id}/status — Polling Endpoint

```python
@router.get("/check/{txn_id}/status")
async def get_check_status(txn_id: str, db: AsyncSession = Depends(get_db)) -> CheckStatus:
    """Returns current status. Frontend polls this every 2s during analysis."""
```

### GET /check/{txn_id}/stream — SSE Stream

```python
@router.get("/check/{txn_id}/stream")
async def stream_check_progress(txn_id: str, db: AsyncSession = Depends(get_db)):
    """
    Server-Sent Events stream of agent progress.
    Use sse_starlette.sse.EventSourceResponse.
    
    Poll the Band room every second. When a new message appears, emit an SSE event:
    {
      "event": "agent_update",
      "data": {
        "agent": "destination_intelligence",
        "status": "complete",
        "risk_level": "HIGH",
        "narrative_preview": "first 100 chars of narrative..."
      }
    }
    
    When verdict is ready, emit:
    {"event": "complete", "data": {verdict, risk_score, txn_id}}
    
    When HITL is needed:
    {"event": "hitl_required", "data": {question, txn_id}}
    
    Close the stream after "complete" or after 5 minutes.
    """
```

---

## Task 3: Build api/routes/report.py

### GET /report/{txn_id}

```python
@router.get("/report/{txn_id}")
async def get_report(txn_id: str, db: AsyncSession = Depends(get_db)):
    """
    Returns the full analysis report for a completed check.
    Used by the shareable report page.
    Returns full CheckRecord data + all agent narratives + price intelligence.
    404 if txn_id not found.
    """
```

---

## Task 4: Build api/routes/history.py

### GET /history

```python
@router.get("/history")
async def get_history(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """
    Returns the last {limit} completed checks in reverse chronological order.
    Returns: list of {txn_id, verdict, risk_score, amount, product_description, 
                       source_type, created_at, report_url, avoided_fraud_estimate}
    Also returns aggregate stats: {total_checks, danger_count, verify_count, safe_count, total_fraud_avoided}
    """
```

---

## Task 5: Build api/main.py

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routes import check, report, history
from api.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="PayGuard AI",
    description="Pre-payment fraud intelligence system",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(check.router, prefix="/api", tags=["check"])
app.include_router(report.router, prefix="/api", tags=["report"])
app.include_router(history.router, prefix="/api", tags=["history"])

@app.get("/health")
async def health(): return {"status": "ok"}
```

---

## Task 6: End-to-End API Test

```bash
# Start server
uvicorn api.main:app --reload --port 8000

# Test 1: Simple check
curl -X POST http://localhost:8000/api/check \
  -F "payment_url=https://razorpay.com" \
  -F "amount=500" \
  -F "source_type=website"

# Test 2: With product and suspicious source
curl -X POST http://localhost:8000/api/check \
  -F "upi_id=random123@ybl" \
  -F "amount=9999" \
  -F "product_description=iPhone 15 Pro" \
  -F "source_type=whatsapp_unknown" \
  -F "additional_context=Someone offered iPhone at great discount"

# Test 3: History
curl http://localhost:8000/api/history

# Test 4: SSE stream (open in browser or use curl)
curl -N http://localhost:8000/api/check/{txn_id}/stream
```

---

## Completion Criteria
- [ ] `POST /api/check` completes the full 4-agent pipeline and returns a verdict
- [ ] `GET /api/check/{txn_id}/stream` SSE stream emits events as agents complete
- [ ] `GET /api/report/{txn_id}` returns full report data
- [ ] `GET /api/history` returns past checks with aggregate stats
- [ ] `POST /api/check/{txn_id}/respond` resumes pipeline after HITL
- [ ] CORS configured for Vite dev server (port 5173)
- [ ] All endpoints return proper HTTP error codes (400 for validation, 404 for not found)
- [ ] Database persists checks across server restarts
