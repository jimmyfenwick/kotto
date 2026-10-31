"""Run from an installed checkout; credentials come from the process environment."""

import asyncio
import os
from contextlib import aclosing
from kotto import Settings, create_agent


async def main():
    async with create_agent(Settings.from_env(os.environ)) as agent:
        async with aclosing(
            agent.run("List the workspace and explain what files are present.")
        ) as events:
            async for event in events:
                if event.kind == "text_delta":
                    print(event.data["text"], end="", flush=True)
                if event.kind == "run_end":
                    print("\nRun ended:", event.data["reason"])


if __name__ == "__main__":
    asyncio.run(main())
