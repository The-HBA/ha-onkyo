"""Helpers for the library tests: a simulated TX-RZ50 on a local port and short timings."""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from custom_components.onkyo_eiscp.lib import Timing
from tools.eiscp_sim import Receiver as Simulated
from tools.eiscp_sim import SimServer

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tx-rz50"
SPEED = 10.0
"""The simulator clock runs this much faster, so its 3 s mode lock lasts 0.3 s."""

FAST = Timing(
    keepalive_interval=0.3,
    keepalive_timeout=0.3,
    backoff=(0.05, 0.1),
    mode_spacing=0.35,
    audio_spacing=0.1,
    reread_delay=0.05,
    power_on_delay=0.1,
    power_on_retries=(0.3, 0.6),
    volume_restore_delay=0.1,
    query_timeout=0.3,
    read_back_delay=0.03,
    probe_spacing=0.001,
    probe_settle=0.1,
)


async def poll(done: Callable[[], bool], seconds: float = 3.0) -> None:
    """Wait until ``done()`` is true."""
    async with asyncio.timeout(seconds):
        while not done():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def fast_clock() -> float:
    return time.monotonic() * SPEED


def make_sim(**options: float | bool) -> SimServer:
    return SimServer(Simulated.from_folder(FIXTURE, fast_clock), **options)  # type: ignore[arg-type]
