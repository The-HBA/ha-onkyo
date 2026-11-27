"""The one object per receiver (contract C3): connection, capabilities, values, timing rules.

Everything the TX-RZ50 taught us is applied here so the integration does not repeat it:

- one connection per host, kept alive, reconnected with backoff;
- listening mode sets wait until the receiver accepts them and are retried once;
- settings that depend on the input or mode are read again after a change;
- a code that answers ``N/A`` (or whose set was refused) is reported as unavailable;
- the volume is put back after power-on (the receiver jumps to -20 dB).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import Counter
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .capabilities import Capabilities, probe, queryable_codes, read_codes, supported_codes
from .client import DEFAULT_PORT, NOT_AVAILABLE, EiscpClient
from .commands import COMMANDS, Reply
from .exceptions import (
    ConnectionClosedError,
    EiscpError,
    NoReplyError,
    NotAvailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable, Mapping

    from .frame import Message

_LOGGER = logging.getLogger(__name__)

ALL_CHANGED: Final = "*"
"""Reported in ``changed`` when everything may have changed (a reconnect, new capabilities)."""
SPACED_CODES: Final = frozenset({"LMD"})
"""Codes the receiver ignores right after a context change or an audio setting write."""
CONTEXT_CODES: Final = frozenset(code for code, command in COMMANDS.items() if command.context)
AUDIO_CODES: Final = frozenset(
    code for code, command in COMMANDS.items() if command.reread and not command.context
)
NEVER_STORED: Final = frozenset({"NRI"})
VOLUME: Final = "MVL"
POWER: Final = "PWR"
MODE: Final = "LMD"
STANDBY: Final = "00"
ON: Final = "01"
VOLUME_RETRIES: Final = 3
CONNECT_TIMEOUT: Final = 5.0
NEVER: Final = float("-inf")


@dataclass(frozen=True, slots=True, kw_only=True)
class Timing:
    """The receiver's timing rules in seconds; tests shorten them."""

    keepalive_interval: float = 60.0
    keepalive_timeout: float = 10.0
    backoff: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
    """Delays between reconnect attempts; the last one repeats."""
    mode_spacing: float = 3.5
    """An ``LMD`` set waits this long after the last context change (and is retried after it)."""
    audio_spacing: float = 1.0
    """An ``LMD`` set waits this long after the last audio setting write."""
    reread_delay: float = 1.5
    power_on_delay: float = 3.0
    power_on_retries: tuple[float, ...] = (10.0, 20.0)
    """Seconds after the ``PWR01`` push at which codes that stayed silent are asked again."""
    volume_restore_delay: float = 3.0
    query_timeout: float = 2.0
    read_back_delay: float = 0.3
    probe_spacing: float = 0.01
    probe_settle: float = 2.0


class Receiver:
    """One receiver: start it, read ``values``, call ``set``, listen for changes."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        restore_volume: bool = True,
        timing: Timing | None = None,
    ) -> None:
        """Remember the address; call ``start`` to connect."""
        self.host = host
        self.port = port
        self.restore_volume = restore_volume
        self.timing = timing or Timing()
        self._client: EiscpClient | None = None
        self._capabilities: Capabilities | None = None
        self._values: dict[str, str] = {}
        self._na: set[str] = set()
        self._refused: set[tuple[str, str]] = set()
        self._sets_in_flight: Counter[str] = Counter()
        self._listeners: list[Callable[[frozenset[str]], None]] = []
        self._pending: set[str] = set()
        self._flush_handle: asyncio.Handle | None = None
        self._last_unavailable: frozenset[str] = frozenset()
        self._connected = False
        self._probing = False
        self._stopping = False
        self._last_context = NEVER
        self._last_audio = NEVER
        self._standby_volume: str | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._supervisor: asyncio.Task[None] | None = None
        self._keepalive: asyncio.Task[None] | None = None
        self._reread_task: asyncio.Task[None] | None = None
        self._power_tasks: list[asyncio.Task[None]] = []

    # ----- state ----------------------------------------------------------------------------

    @property
    def capabilities(self) -> Capabilities:
        """What the receiver supports (after ``start``)."""
        if self._capabilities is None:
            msg = "the receiver is not started"
            raise EiscpError(msg)
        return self._capabilities

    @property
    def connected(self) -> bool:
        """True while the connection is open and the receiver has been probed."""
        return self._connected and self._client is not None and self._client.connected

    @property
    def values(self) -> Mapping[str, str]:
        """The last value of each code; a code that answered ``N/A`` is not in it."""
        return MappingProxyType(dict(self._values))

    @property
    def unavailable(self) -> frozenset[str]:
        """Codes that answered ``N/A``, and codes refused under the current listening mode."""
        mode = self._values.get(MODE)
        return frozenset(self._na | {code for code, at in self._refused if at == mode})

    def add_listener(self, callback: Callable[[frozenset[str]], None]) -> Callable[[], None]:
        """Call ``callback(changed)`` after each batch of messages that changed something.

        ``changed`` holds the codes whose value or availability changed; ``{"*"}`` means
        everything (the connection came back or the capabilities changed). Returns a function
        that removes the listener.
        """
        self._listeners.append(callback)

        def remove() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return remove

    # ----- start and stop -------------------------------------------------------------------

    async def start(self) -> Capabilities:
        """Connect, probe, and keep the connection alive. Raises ``EiscpError`` on failure."""
        if self._client is not None:
            msg = "the receiver is already started"
            raise EiscpError(msg)
        self._stopping = False
        client = self._new_client()
        self._client = client
        self._probing = True
        try:
            await self._connect_and_probe(client)
        except BaseException:
            self._client = None
            await client.close()
            raise
        finally:
            self._probing = False
        self._connected = True
        self._remember_standby_volume()
        self._supervisor = asyncio.create_task(self._supervise())
        self._keepalive = asyncio.create_task(self._keep_alive(client))
        return self.capabilities

    async def stop(self) -> None:
        """Close the connection and stop every background task."""
        self._stopping = True
        self._connected = False
        if self._flush_handle is not None:  # no report after stop
            self._flush_handle.cancel()
            self._flush_handle = None
        tasks = [*self._tasks, *(t for t in (self._supervisor, self._keepalive) if t)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._supervisor = self._keepalive = self._reread_task = None
        self._power_tasks.clear()
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _new_client(self) -> EiscpClient:
        client = EiscpClient(self.host, self.port)
        client.add_listener(self._on_message)
        return client

    async def _connect_and_probe(self, client: EiscpClient) -> None:
        """Open the connection and read what it supports; one failure type for callers."""
        self._na.clear()
        self._refused.clear()
        try:
            await client.connect(CONNECT_TIMEOUT)
            self._capabilities = await probe(
                client, spacing=self.timing.probe_spacing, settle=self.timing.probe_settle
            )
        except (OSError, TimeoutError) as err:
            msg = f"cannot reach {self.host}:{self.port}: {err}"
            raise ConnectionClosedError(msg) from err

    # ----- queries and sets -----------------------------------------------------------------

    async def query(self, code: str) -> str:
        """Ask for ``code``; returns the parameter (``N/A`` included)."""
        command = COMMANDS.get(code)
        if command is not None and command.never_query:
            msg = f"{code} must not be queried (it shows a popup on the receiver)"
            raise ValueError(msg)
        return await self._require_client().query(code, self.timing.query_timeout)

    async def set(self, code: str, param: str) -> str:
        """Set ``code`` and return the reply (or the read back).

        Raises ``NotAvailableError`` when the receiver refuses (the code is then unavailable
        under the current listening mode) and ``NoReplyError`` when it ignores the set.
        """
        command = COMMANDS.get(code)
        if command is not None and command.never_set:
            msg = f"{code} must not be set (side effects, or a status)"
            raise ValueError(msg)
        client = self._require_client()
        if code in SPACED_CODES:
            await self._wait_for_spacing()
        self._sets_in_flight[code] += 1
        try:
            try:
                reply = await self._send_set(client, code, param)
            except NoReplyError:
                if code not in SPACED_CODES:
                    raise
                await asyncio.sleep(self.timing.mode_spacing)  # the receiver was still busy
                reply = await self._send_set(client, code, param)
        except NotAvailableError:
            self._refused.add((code, self._values.get(MODE, "")))
            self._mark(code)
            raise
        finally:
            self._sets_in_flight[code] -= 1
        if (code, self._values.get(MODE, "")) in self._refused:
            self._refused.discard((code, self._values.get(MODE, "")))
            self._mark(code)
        if code in AUDIO_CODES:
            self._last_audio = asyncio.get_running_loop().time()
        return reply

    async def send_raw(self, message: str, wait: float = 1.0) -> list[str]:
        """Send any message (admin only) and return every message seen in the next ``wait`` s."""
        client = self._require_client()
        seen: list[str] = []
        remove = client.add_listener(lambda message: seen.append(message.code + message.param))
        try:
            await client.send(message)
            await asyncio.sleep(wait)
        finally:
            remove()
        return seen

    def _require_client(self) -> EiscpClient:
        if self._client is None or not self.connected:
            msg = "not connected to the receiver"
            raise ConnectionClosedError(msg)
        return self._client

    async def _send_set(self, client: EiscpClient, code: str, param: str) -> str:
        command = COMMANDS.get(code)
        mode = command.reply if command is not None else Reply.ECHO
        timeout = self.timing.query_timeout
        if mode is Reply.ECHO:
            return await client.set(code, param, timeout)
        refused = False

        def watch(message: Message) -> None:
            nonlocal refused
            refused = refused or (message.code == code and message.param == NOT_AVAILABLE)

        remove = client.add_listener(watch)
        try:
            await client.command(code, param)
            if mode is Reply.NONE:
                return ""
            await asyncio.sleep(self.timing.read_back_delay)
        finally:
            remove()
        reply = await client.query(code, timeout)
        if refused or reply == NOT_AVAILABLE:
            raise NotAvailableError(code, param)
        return reply

    async def _wait_for_spacing(self) -> None:
        """Wait until the receiver accepts a mode set again (3.5 s and 1 s rules)."""
        loop = asyncio.get_running_loop()
        ready = max(
            self._last_context + self.timing.mode_spacing,
            self._last_audio + self.timing.audio_spacing,
        )
        if (delay := ready - loop.time()) > 0:
            await asyncio.sleep(delay)
            # a change during the wait moves the time again
            await self._wait_for_spacing()

    # ----- messages -------------------------------------------------------------------------

    def _on_message(self, message: Message) -> None:
        code, param = message.code, message.param
        if param == NOT_AVAILABLE:
            if self._sets_in_flight[code] > 0:
                return  # a refused set: ``set`` handles it per listening mode
            if code not in self._na:
                self._na.add(code)
                self._values.pop(code, None)
                self._mark(code)
            return
        if code in NEVER_STORED:
            return
        if code in self._na:
            self._na.discard(code)
            self._mark(code)
        old = self._values.get(code)
        if old == param:
            return
        self._values[code] = param
        self._mark(code)
        if not self._probing:
            self._on_change(code, old, param)

    def _on_change(self, code: str, old: str | None, new: str) -> None:
        now = asyncio.get_running_loop().time()
        if code in CONTEXT_CODES:
            self._last_context = now
        if code in AUDIO_CODES:
            self._last_audio = now
        if code == POWER:
            self._on_power(old, new)
        elif code in CONTEXT_CODES:
            self._schedule_reread()

    def _on_power(self, old: str | None, new: str) -> None:
        self._cancel_power_tasks()
        if new == STANDBY:
            if old == ON:
                self._standby_volume = self._values.get(VOLUME)
            self._schedule_reread()
            return
        was_standby = old == STANDBY
        if self._reread_task is not None:
            self._reread_task.cancel()
        self._power_tasks.append(self._spawn(self._refresh_after_power_on()))
        if was_standby and self.restore_volume and self._standby_volume is not None:
            self._power_tasks.append(self._spawn(self._put_volume_back(self._standby_volume)))

    def _cancel_power_tasks(self) -> None:
        for task in self._power_tasks:
            task.cancel()
        self._power_tasks.clear()

    def _remember_standby_volume(self) -> None:
        if self._values.get(POWER) == STANDBY:
            self._standby_volume = self._values.get(VOLUME)

    # ----- change notification --------------------------------------------------------------

    def _mark(self, *codes: str) -> None:
        self._pending.update(codes)
        if self._flush_handle is None:
            self._flush_handle = asyncio.get_running_loop().call_soon(self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        changed = set(self._pending)
        self._pending.clear()
        unavailable = self.unavailable
        changed |= unavailable ^ self._last_unavailable
        self._last_unavailable = unavailable
        for callback in list(self._listeners):
            try:
                callback(frozenset(changed))
            except Exception:
                _LOGGER.exception("receiver listener failed")

    # ----- background work ------------------------------------------------------------------

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _LOGGER.error("background task failed", exc_info=error)

    def _schedule_reread(self) -> None:
        if self._reread_task is not None:
            self._reread_task.cancel()
        self._reread_task = self._spawn(self._reread())

    def _reread_codes(self) -> list[str]:
        supported = self.capabilities.supported
        return [
            code
            for code, command in COMMANDS.items()
            if command.reread and code in supported and not command.never_query
        ]

    async def _reread(self) -> None:
        """Read the settings that depend on power, input, mode or Dirac slot again."""
        await asyncio.sleep(self.timing.reread_delay)
        await self._read(self._reread_codes())

    async def _read(self, codes: Iterable[str]) -> list[str]:
        """Query ``codes`` side by side at probe spacing; returns the ones that stayed silent."""
        client = self._client
        if client is None:
            return []

        async def one(code: str, delay: float) -> str | None:
            await asyncio.sleep(delay)
            try:
                await client.query(code, self.timing.query_timeout)
            except NoReplyError:
                return code
            except ConnectionClosedError:
                return None
            return None

        results = await asyncio.gather(
            *(one(code, index * self.timing.probe_spacing) for index, code in enumerate(codes))
        )
        return [code for code in results if code is not None]

    async def _refresh_after_power_on(self) -> None:
        """After ``PWR01`` the receiver answers late: read the settings again, then everything."""
        timing = self.timing
        await asyncio.sleep(timing.power_on_delay)
        silent = await self._read(self._reread_codes())
        elapsed = timing.power_on_delay
        for at in timing.power_on_retries:
            if not silent:
                break
            await asyncio.sleep(max(at - elapsed, 0.0))
            elapsed = max(at, elapsed)
            silent = await self._read(silent)
        await self._read_everything()

    async def _read_everything(self) -> None:
        client = self._client
        if client is None or not client.connected:
            return
        answers = await read_codes(
            client,
            (code for code in queryable_codes() if code != "NRI"),
            spacing=self.timing.probe_spacing,
            settle=self.timing.probe_settle,
        )
        capabilities = self.capabilities
        supported = capabilities.supported | supported_codes(answers)
        if supported != capabilities.supported:
            self._capabilities = replace(
                capabilities,
                supported=supported,
                values=MappingProxyType({**capabilities.values, **answers}),
            )
            self._mark(ALL_CHANGED)

    async def _put_volume_back(self, volume: str) -> None:
        """Set the old volume 3 s after ``PWR01`` (the receiver jumps to -20 dB at power-on)."""
        await asyncio.sleep(self.timing.volume_restore_delay)
        try:
            wanted = int(volume, 16)
            current = int(self._values.get(VOLUME, volume), 16)
        except ValueError:
            return
        if current <= wanted:
            return
        for _ in range(VOLUME_RETRIES):
            try:
                await self.set(VOLUME, volume)
            except NoReplyError:
                continue
            except EiscpError:
                return
            return
        _LOGGER.warning("could not put the volume back to %s after power-on", volume)

    # ----- connection supervision -----------------------------------------------------------

    async def _keep_alive(self, client: EiscpClient) -> None:
        """Ask for the power state every minute; no answer means the connection is dead."""
        timing = self.timing
        while client.connected:
            await asyncio.sleep(timing.keepalive_interval)
            try:
                await client.query(POWER, timing.keepalive_timeout)
            except NoReplyError:
                _LOGGER.warning("no answer from %s, closing the connection", self.host)
                await client.close()
                return
            except ConnectionClosedError:
                return

    async def _supervise(self) -> None:
        """When the connection closes, reconnect with backoff and probe again."""
        while not self._stopping:
            client = self._client
            if client is None:  # pragma: no cover  (stop() cancels this task first)
                return
            await client.wait_closed()
            if self._stopping:  # pragma: no cover  (stop() cancels this task first)
                return
            self._connected = False
            self._cancel_power_tasks()
            if self._keepalive is not None:
                self._keepalive.cancel()
            _LOGGER.warning("connection to %s lost: %s", self.host, client.close_reason)
            self._mark(ALL_CHANGED)
            await client.close()
            await self._reconnect()

    async def _reconnect(self) -> None:
        delays = itertools.chain(self.timing.backoff, itertools.repeat(self.timing.backoff[-1]))
        for delay in delays:
            await asyncio.sleep(delay)
            client = self._new_client()
            self._probing = True
            try:
                await self._connect_and_probe(client)
            except (EiscpError, OSError, TimeoutError) as err:
                _LOGGER.debug("reconnect to %s failed: %s", self.host, err)
                await client.close()
                continue
            finally:
                self._probing = False
            self._client = client
            self._connected = True
            self._remember_standby_volume()
            self._keepalive = asyncio.create_task(self._keep_alive(client))
            self._mark(ALL_CHANGED)
            return
