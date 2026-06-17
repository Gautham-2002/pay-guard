"""Transaction-scoped QR image artifact storage.

Band messages should carry durable context, not large binary payloads.  This
module stores uploaded QR bytes on the app host and passes a small reference
through the Band room so Agent 2 can load the original image when it runs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


_SAFE_ID = re.compile(r"[^a-zA-Z0-9_.-]+")
_DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts" / "qr"


def _artifact_root() -> Path:
    configured = os.getenv("PAYGUARD_QR_ARTIFACT_DIR")
    return Path(configured).expanduser().resolve() if configured else _DEFAULT_ARTIFACT_DIR


def _safe_txn_id(txn_id: str) -> str:
    cleaned = _SAFE_ID.sub("_", txn_id).strip("._")
    if not cleaned:
        raise ValueError("txn_id must contain at least one safe filename character")
    return cleaned


def build_qr_artifact_ref(txn_id: str) -> str:
    """Return the stable artifact reference for a transaction."""
    return f"qr:{_safe_txn_id(txn_id)}"


def _path_for_ref(artifact_ref: str) -> Path:
    if not artifact_ref.startswith("qr:"):
        raise ValueError(f"Unsupported QR artifact reference: {artifact_ref!r}")
    txn_id = _safe_txn_id(artifact_ref.removeprefix("qr:"))
    root = _artifact_root()
    path = (root / f"{txn_id}.bin").resolve()
    if root.resolve() not in path.parents:
        raise ValueError("QR artifact reference resolved outside artifact root")
    return path


def save_qr_artifact(txn_id: str, data: bytes | None) -> str | None:
    """Persist QR image bytes and return a Band-safe reference."""
    if not data:
        return None
    artifact_ref = build_qr_artifact_ref(txn_id)
    path = _path_for_ref(artifact_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return artifact_ref


def load_qr_artifact(artifact_ref: str | None) -> bytes | None:
    """Load QR image bytes from a previously generated artifact reference."""
    if not artifact_ref:
        return None
    path = _path_for_ref(artifact_ref)
    if not path.exists():
        raise FileNotFoundError(f"QR artifact not found: {artifact_ref}")
    return path.read_bytes()
