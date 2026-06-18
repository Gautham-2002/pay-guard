"""Band remote runner for Agent 4 — Verdict Synthesis."""

from __future__ import annotations

import asyncio

from agents.remote_runtime import run_cli, run_remote_agent


async def main() -> None:
    await run_remote_agent(
        config_key="verdict_synthesis",
    )


def cli() -> None:
    run_cli(
        config_key="verdict_synthesis",
    )


if __name__ == "__main__":
    asyncio.run(main())
