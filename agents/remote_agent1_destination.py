"""Band remote runner for Agent 1 — Destination Intelligence."""

from __future__ import annotations

import asyncio

from agents.remote_runtime import run_cli, run_remote_agent


async def main() -> None:
    await run_remote_agent(
        config_key="destination_intelligence",
    )


def cli() -> None:
    run_cli(
        config_key="destination_intelligence",
    )


if __name__ == "__main__":
    asyncio.run(main())
