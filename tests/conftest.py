import asyncio
import sys

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    # aiodns (pulled in by aiohttp) cannot run on Windows' default proactor loop.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
