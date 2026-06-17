"""Band remote runner for Agent 2 — QR Decode & UPI Validator."""

from __future__ import annotations

import asyncio

from agents.remote_runtime import run_cli, run_remote_agent


async def main() -> None:
    await run_remote_agent(
        config_key="qr_upi_validator",
    )


def cli() -> None:
    run_cli(
        config_key="qr_upi_validator",
    )


if __name__ == "__main__":
    asyncio.run(main())
