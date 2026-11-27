"""Fixtures for the library tests: a simulated TX-RZ50 and a started receiver."""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from lib_helpers import FAST, make_sim

from custom_components.onkyo_eiscp.lib import Receiver as Library

if TYPE_CHECKING:
    from tools.eiscp_sim import SimServer


@pytest.fixture
async def sim() -> AsyncIterator[SimServer]:
    server = make_sim()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def receiver(sim: SimServer) -> AsyncIterator[Library]:
    library = Library("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    yield library
    await library.stop()
