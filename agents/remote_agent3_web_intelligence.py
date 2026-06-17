"""Band remote runner for Agent 3 — Web Intelligence."""

from __future__ import annotations

import asyncio

from agents.remote_runtime import run_cli, run_remote_agent


async def main() -> None:
    await run_remote_agent(
        config_key="web_intelligence",
    )


def cli() -> None:
    run_cli(
        config_key="web_intelligence",
    )


if __name__ == "__main__":
    asyncio.run(main())
