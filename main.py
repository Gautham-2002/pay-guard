"""
PayGuard AI — Root Entry Point
================================
Convenience launcher: `uv run python main.py` starts the FastAPI dev server.
For production use: `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`
"""

import os

from dotenv import load_dotenv

# Load environment variables from .env before importing any services
load_dotenv()

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", 8000))
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )
