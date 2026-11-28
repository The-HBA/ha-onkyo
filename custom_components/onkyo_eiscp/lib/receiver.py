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

from . import ci
from .capabilities import Capabilities, probe, queryable_codes, read_codes, supported_codes
from .client import DEFAULT_PORT, NOT_AVAILABLE, EiscpClient
from .commands import COMMANDS, Reply, Value
from .exceptions import (
    CiNotAppliedError,
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
        self._refused_options: set[tuple[str, str, str]] = set()
        self._sets_in_flight: Counter[str] = Counter()
        self._listeners: list[Callable[[frozenset[str]], None]] = []
        self._pending: set[str] = set()
        self._flush_handle: asyncio.Handle | None = None
        self._last_unavailable: frozenset[str] = frozenset()
        self._last_options: Mapping[str, frozenset[str]] = {}
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
        self._reread_wanted = False
        self._ci_lock = asyncio.Lock()

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

    @property
    def refused_options(self) -> Mapping[str, frozenset[str]]:
        """Parameters of multi-option codes (``LTN``, ``DIM``) refused under the current mode.

        A refused option does not make the whole code unavailable: ``LTN02`` is refused with PCM
        while ``LTN01`` works. Switches and numbers (two options or none) are reported through
        ``unavailable`` instead.
        """
        mode = self._values.get(MODE)
        found: dict[str, set[str]] = {}
        for code, param, at in self._refused_options:
            if at == mode:
                found.setdefault(code, set()).add(param)
        return {code: frozenset(params) for code, params in found.items()}

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
        self._refused_options.clear()
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
            mode = self._values.get(MODE, "")
            if _option_level(code):
                self._refused_options.add((code, param, mode))
            else:
                self._refused.add((code, mode))
            self._mark(code)
            raise
        finally:
            self._sets_in_flight[code] -= 1
        mode = self._values.get(MODE, "")
        if (code, mode) in self._refused or (code, param, mode) in self._refused_options:
            self._refused.discard((code, mode))
            self._refused_options.discard((code, param, mode))
            self._mark(code)
        if code in AUDIO_CODES:
            self._last_audio = asyncio.get_running_loop().time()
        return reply

    # ----- CI config commands (specs/web-setup-backup.md) -----------------------------------

    async def ci_read(self, code: str, key: Mapping[str, str] | None = None) -> ci.CiRecord:
        """Read one CI record, for example ``ci_read("LCC", {"MM": "MM1"})``.

        A family with a key (selector, preset ...) stays silent without it, so ``key`` is
        required for those. Raises ``NoReplyError`` when the receiver does not answer.
        """
        message = ci.query_message(code, key)
        param = await self._require_client().request(
            message, ci.reply_code(code), self.timing.query_timeout
        )
        record = ci.decode(ci.reply_code(code) + param)
        wanted = {name: value.strip() for name, value in (key or {}).items()}
        if record.key != wanted:
            # a late reply to an earlier read of another record: never use it
            raise NoReplyError(ci.reply_code(code), message)
        return record

    async def ci_set(
        self, code: str, changes: Mapping[str, str], key: Mapping[str, str] | None = None
    ) -> ci.CiChange:
        """Set some fields of one CI record, read it back and return the change.

        The record is read first, so the returned ``CiChange`` holds the old values and
        ``restore_message``; use ``ci_restore`` to put them back (do this for the calibration
        families LCC, SDC and COC, RULES 7 and 17). Raises ``CiRefusedError`` for a read-only
        family or field and ``CiNotAppliedError`` when the receiver ignored the set.
        """
        client = self._require_client()
        async with self._ci_lock:
            before = await self.ci_read(code, key)
            change = ci.plan_set(before, changes, key)
            await client.send(change.set_message)
            try:
                after = await self._ci_read_back(change)
            except EiscpError as err:
                # The set went out: the caller still needs the old values to offer a restore.
                err.change = change  # type: ignore[attr-defined]
                raise
            change = replace(change, after=after)
            if not ci.applied(after, change.changes):
                raise CiNotAppliedError(code, change.set_message, change)
            return change

    async def ci_restore(self, change: ci.CiChange) -> ci.CiRecord:
        """Put the old values of ``change`` back and return the record read back."""
        client = self._require_client()
        async with self._ci_lock:
            await client.send(change.restore_message)
            after = await self._ci_read_back(change)
            if not ci.applied(after, change.old):
                raise CiNotAppliedError(
                    change.code, change.restore_message, replace(change, after=after)
                )
            return after

    async def _ci_read_back(self, change: ci.CiChange) -> ci.CiRecord:
        await asyncio.sleep(self.timing.read_back_delay)
        return await self.ci_read(change.code, change.key)

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
        if code.startswith(ci.PREFIX):
            return  # CI records are read on demand, never kept as state
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
        self._reread_wanted = False

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
        options = self.refused_options
        changed |= {
            code
            for code in options.keys() | self._last_options.keys()
            if options.get(code) != self._last_options.get(code)
        }
        self._last_options = options
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
        if any(not task.done() for task in self._power_tasks):
            self._reread_wanted = True  # the power-on work ends with one more re-read
            return
        self._start_reread()

    def _start_reread(self) -> None:
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
        if self._reread_wanted:  # the input or mode changed while this ran
            self._reread_wanted = False
            self._start_reread()  # this task is still in _power_tasks, so no check

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

    def _drop_stale_values(self) -> None:
        """After a reconnect, forget known codes that did not answer the new probe."""
        answered = self.capabilities.values
        for code in [c for c in self._values if c in COMMANDS and c not in answered]:
            del self._values[code]
            self._mark(code)

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
            except BaseException:  # stop() cancels this task: do not leave the connection open
                await client.close()
                raise
            finally:
                self._probing = False
            self._drop_stale_values()
            self._client = client
            self._connected = True
            self._remember_standby_volume()
            self._keepalive = asyncio.create_task(self._keep_alive(client))
            _LOGGER.info("connection to %s is back", self.host)
            self._mark(ALL_CHANGED)
            return


def _option_level(code: str) -> bool:
    """Say whether a refusal means one parameter is refused, not the whole code.

    That is every code that is not a plain switch or a number: enums with more than two options
    (``LTN``, ``DIM``) and enums without a list (``SLI``, ``LMD``).
    """
    command = COMMANDS.get(code)
    if command is None or command.value is not Value.ENUM:
        return False
    return len(command.options) != 2  # noqa: PLR2004
