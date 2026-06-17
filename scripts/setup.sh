#!/usr/bin/env bash
# =============================================================================
# PayGuard AI — Project Setup Script
# =============================================================================
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
#
# What this does:
#   1. Checks required system tools (uv, git)
#   2. Pins Python 3.11 and creates the virtual environment via uv sync
#   3. Installs Playwright Chromium browser
#   4. Copies .env.example → .env (if .env doesn't exist)
#   5. Runs all Phase 0 completion checks
#   6. Prints a summary with next steps
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[✅ OK]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERR]${RESET}   $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║        🛡️  PayGuard AI — Setup           ║${RESET}"
echo -e "${BOLD}${CYAN}║   Band of Agents Hackathon · June 2026   ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"
echo ""

# Change to project root (one level up from scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
info "Project root: $PROJECT_ROOT"

# =============================================================================
# Step 1 — Check required tools
# =============================================================================
echo ""
echo -e "${BOLD}Step 1 — Checking required tools${RESET}"
echo "────────────────────────────────"

check_tool() {
    local tool="$1"
    if command -v "$tool" &>/dev/null; then
        success "$tool found: $(command -v "$tool")"
    else
        die "$tool not found. Please install it first."
    fi
}

check_tool uv
check_tool git
check_tool python3

# =============================================================================
# Step 2 — Pin Python version and install dependencies
# =============================================================================
echo ""
echo -e "${BOLD}Step 2 — Installing Python dependencies (uv sync)${RESET}"
echo "──────────────────────────────────────────────────"

# Ensure .python-version is set
if [[ "$(cat .python-version 2>/dev/null | tr -d '[:space:]')" != "3.11" ]]; then
    info "Writing .python-version = 3.11"
    echo "3.11" > .python-version
fi
success ".python-version = 3.11"

info "Running uv sync (this may take a few minutes on first run)..."
if uv sync 2>&1; then
    success "All dependencies installed"
else
    die "uv sync failed — check the output above"
fi

# Confirm Python version in use
PY_VERSION=$(uv run python --version 2>&1)
success "Python in use: $PY_VERSION"

# =============================================================================
# Step 3 — Install Playwright Chromium
# =============================================================================
echo ""
echo -e "${BOLD}Step 3 — Installing system libraries${RESET}"
echo "──────────────────────────────────────"

# libzbar0 is required by pyzbar for local QR code decoding (Agent 2)
info "Installing libzbar0 (required by pyzbar for QR decoding)..."
if command -v apt-get &>/dev/null; then
    if sudo apt-get install -y libzbar0 2>&1 | grep -q "installed"; then
        success "libzbar0 installed"
    else
        # May already be installed — check
        if dpkg -l libzbar0 2>/dev/null | grep -q '^ii'; then
            success "libzbar0 already installed"
        else
            warn "libzbar0 install may have failed — QR local decode will fall back to AIML API vision"
        fi
    fi
elif command -v brew &>/dev/null; then
    # macOS
    if brew list zbar &>/dev/null; then
        success "zbar already installed (macOS)"
    else
        brew install zbar && success "zbar installed via Homebrew" || \
            warn "brew install zbar failed — QR local decode will fall back to AIML API vision"
    fi
else
    warn "Cannot detect package manager. Install libzbar0 manually if QR local decode fails."
    warn "  Ubuntu/Debian: sudo apt-get install libzbar0"
    warn "  macOS:         brew install zbar"
fi

# Install Playwright Chromium browser
echo ""
echo -e "${BOLD}Step 3b — Installing Playwright Chromium browser${RESET}"
echo "──────────────────────────────────────────────────"
info "Downloading Chromium (~160 MB, skipped if already cached)..."

if uv run playwright install chromium 2>&1; then
    success "Playwright Chromium installed"
else
    die "playwright install chromium failed — check the output above"
fi

# =============================================================================
# Step 4 — Set up .env file
# =============================================================================
echo ""
echo -e "${BOLD}Step 4 — Environment configuration${RESET}"
echo "────────────────────────────────────"

if [[ -f ".env" ]]; then
    success ".env already exists — skipping copy"
else
    cp .env.example .env
    success ".env created from .env.example"
    warn "⚠️  Fill in your API keys in .env before running agents!"
    warn "   Required: BAND_API_KEY, FEATHERLESS_API_KEY, AIML_API_KEY"
    warn "   Required: VIRUSTOTAL_API_KEY, WHOISJSON_KEY"
    warn "   Optional: GOOGLE_SAFE_BROWSING_KEY with ENABLE_SAFE_BROWSING=true"
    warn "   Optional: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET with ENABLE_REDDIT=true"
fi

# =============================================================================
# Step 5 — Phase 0 completion checks
# =============================================================================
echo ""
echo -e "${BOLD}Step 5 — Phase 0 completion checks${RESET}"
echo "────────────────────────────────────"

CHECKS_PASSED=0
CHECKS_FAILED=0

run_check() {
    local label="$1"
    local cmd="$2"
    if eval "$cmd" &>/dev/null; then
        success "$label"
        ((CHECKS_PASSED++)) || true
    else
        error "FAILED: $label"
        ((CHECKS_FAILED++)) || true
    fi
}

# 5a. Pydantic models
run_check "api.models — all Pydantic models import" \
    "uv run python -c 'from api.models import CheckRequest, CheckResponse, Agent1Output, Agent2Output, Agent3Output, Agent4Output, HITLMessage, VerdictLevel'"

# 5b. Scam patterns
run_check "data/scam_patterns.json — 6 patterns loaded" \
    "uv run python -c \"import json; d=json.load(open('data/scam_patterns.json')); assert len(d)==6\""

# 5c. UPI deep-link parser (only implemented function in Phase 0)
run_check "services.qr_handler — UPI deep-link parser" \
    "uv run python -c \"from services.qr_handler import parse_upi_deep_link; r=parse_upi_deep_link('upi://pay?pa=m@paytm&am=500'); assert r['pa']=='m@paytm'\""

# 5d. FastAPI app loads
run_check "api.main — FastAPI app loads" \
    "uv run python -c 'from api.main import app; assert app.title==\"PayGuard AI\"'"

# 5e. Playwright headless screenshot
run_check "playwright — headless Chromium screenshot" \
    "uv run python -c \"
import asyncio
from playwright.async_api import async_playwright
async def t():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        pg=await b.new_page()
        await pg.goto('https://example.com',timeout=20000)
        s=await pg.screenshot()
        await b.close()
        assert len(s)>0
asyncio.run(t())
\""

# 5f. All agent stubs present
run_check "agents — all 4 stubs importable" \
    "uv run python -c 'import agents.agent1_destination, agents.agent2_qr_upi, agents.agent3_web_intelligence, agents.agent4_verdict'"

# 5g. All service stubs importable
run_check "services — all 5 stubs importable" \
    "uv run python -c 'import services.band_client, services.featherless_client, services.aiml_client, services.domain_intel, services.qr_handler'"

# 5h. API routes importable
run_check "api.routes — all 3 route stubs importable" \
    "uv run python -c 'from api.routes.check import router; from api.routes.report import router; from api.routes.history import router'"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║              Setup Summary               ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""

TOTAL=$((CHECKS_PASSED + CHECKS_FAILED))
echo -e "  Checks passed : ${GREEN}${BOLD}${CHECKS_PASSED}/${TOTAL}${RESET}"

if [[ $CHECKS_FAILED -gt 0 ]]; then
    echo -e "  Checks failed : ${RED}${BOLD}${CHECKS_FAILED}${RESET}"
    echo ""
    warn "Some checks failed. Review the errors above."
else
    echo ""
    echo -e "${GREEN}${BOLD}  🎉 Phase 0 setup complete!${RESET}"
fi

echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo "  1. Fill in API keys:     nano .env"
echo "  2. Test all connections: uv run python tests/test_connections.py"
echo "  3. Start dev server:     uv run uvicorn api.main:app --reload --port 8000"
echo "  4. API docs:             http://localhost:8000/docs"
echo ""
echo -e "${BOLD}Phase roadmap:${RESET}"
echo "  Phase 1 → Band integration + Agent 1 (Featherless / Llama 3.3 70B)"
echo "  Phase 2 → Agent 2 QR & UPI Validator (AIML API vision)"
echo "  Phase 3 → Agent 3 Web Intelligence (Playwright + DDG + Reddit)"
echo "  Phase 4 → Agent 4 Verdict Synthesis"
echo "  Phase 5 → FastAPI routes + SSE + HITL"
echo "  Phase 6 → Band room end-to-end"
echo "  Phase 7 → React + Vite frontend"
echo "  Phase 8 → Polish + demo + deployment"
echo ""

[[ $CHECKS_FAILED -gt 0 ]] && exit 1 || exit 0
