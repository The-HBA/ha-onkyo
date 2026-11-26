#!/usr/bin/env python3
"""Survey an Onkyo, Pioneer or Integra receiver over eISCP and log what it says.

Everything goes over ONE connection per run: the receiver closes an older connection when the same
host opens a second one. Every message sent and received is appended to a JSONL capture file, one
object per line: ts, conn, dir (tx or rx), raw, code, param, tag, optional text.

Modes:
  read    query codes (each sent with QSTN) and log the replies; read-only
  listen  send nothing, log what the receiver pushes; read-only
  sweep   send every three character code with QSTN in batches and log what answers; read-only
  write   per message: read and record, set, read back, restore, verify (restore protocol)

Run from the repository root, for example:
  python tools/eiscp_survey.py --host 192.0.2.10 --out session.jsonl read PWR NRI
  python tools/eiscp_survey.py --host 192.0.2.10 --out session.jsonl write MVL3C
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import itertools
import json
import os
import string
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.onkyo_eiscp.lib import (
    ConnectionClosedError,
    EiscpClient,
    Message,
    parse_data,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

VOLUME_CODES = frozenset({"MVL", "ZVL", "VL3", "VL4"})
DEFAULT_PORT = 60128
EXIT_REFUSED = 2
EXIT_NOT_RESTORED = 3
EXIT_CONNECTION = 4
RESTORE_RETRY_DELAY = 3.5
HEX_DIGITS = frozenset(string.hexdigits)
# Dirac slot write codes (specs/eiscp-tx-rz50.md): the receiver reports DSS as one digit per slot,
# 2 = active, and takes DSSC00 (off) to DSSC03 (slot 1 to 3).
DSS_TO_WRITE = {"111": "DSSC00", "211": "DSSC01", "121": "DSSC02", "112": "DSSC03"}


class Refused(Exception):  # noqa: N818
    """A write was refused before anything was sent."""


class Session:
    """One connection plus the capture file."""

    def __init__(self, host: str, port: int, out: Path, conn: int, *, quiet: bool = False) -> None:
        self.client = EiscpClient(host, port)
        self.out = out
        self.conn = conn
        self.quiet = quiet
        self.rx_tag = "push"
        self.inbox: list[Message] = []
        self._expect: set[str] = set()
        self._waiters: dict[str, asyncio.Future[Message]] = {}
        self.client.add_listener(self._on_message)

    async def open(self) -> None:
        await self.client.connect()
        self.note(f"connected, conn {self.conn}")

    async def close(self) -> None:
        await self.client.close()

    def log(self, direction: str, raw: str, tag: str, text: str = "") -> None:
        msg = parse_data(raw)
        rec: dict[str, Any] = {
            "ts": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "conn": self.conn,
            "dir": direction,
            "raw": raw,
            "code": msg.code,
            "param": msg.param,
            "tag": tag,
        }
        if text:
            rec["text"] = text
        self._append(rec)
        if not self.quiet:
            stamp = str(rec["ts"])[11:23]
            print(f"{stamp} c{self.conn} {direction} {tag:7} {msg.code}{msg.param[:120]}")

    def note(self, text: str) -> None:
        rec = {
            "ts": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "conn": self.conn,
            "dir": "tx",
            "raw": "",
            "code": "",
            "param": "",
            "tag": "note",
            "text": text,
        }
        self._append(rec)
        print(f"{str(rec['ts'])[11:23]} c{self.conn} note    {text}")

    def _append(self, rec: dict[str, Any]) -> None:
        with self.out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _on_message(self, message: Message) -> None:
        tag = self.rx_tag
        if message.code in self._expect:
            tag = "reply"
        self.log("rx", message.raw, tag)
        self.inbox.append(message)
        waiter = self._waiters.get(message.code)
        if waiter is not None and not waiter.done():
            waiter.set_result(message)

    async def send(self, message: str, tag: str) -> None:
        """Send ``message`` (code plus parameter) and log it."""
        await self.client.send(message)
        self.log("tx", f"!1{message}\r", tag)

    async def request(
        self, message: str, tag: str, reply_code: str, timeout: float
    ) -> Message | None:
        """Send ``message`` and wait up to ``timeout`` seconds for a message with ``reply_code``."""
        waiter: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self._waiters[reply_code] = waiter
        self._expect.add(reply_code)
        try:
            await self.send(message, tag)
            return await asyncio.wait_for(waiter, timeout)
        except TimeoutError:
            return None
        finally:
            self._waiters.pop(reply_code, None)
            self._expect.discard(reply_code)

    async def query(self, code: str, timeout: float, tag: str = "query") -> Message | None:
        return await self.request(f"{code}QSTN", tag, code, timeout)


def read_codes(codes: Sequence[str], codes_file: str | None) -> list[str]:
    result = list(codes)
    if codes_file:
        for line in Path(codes_file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                result.append(line)
    bad = [c for c in result if len(c) != 3 or not c.isalnum()]  # noqa: PLR2004
    if bad:
        msg = f"read mode takes bare three character codes (QSTN is added), got {bad}"
        raise Refused(msg)
    return [c.upper() for c in result]


async def mode_read(session: Session, args: argparse.Namespace) -> int:
    codes = read_codes(args.codes, args.codes_file)
    if not codes:
        msg = "no codes given"
        raise Refused(msg)
    nri_out = Path(args.nri_out) if args.nri_out else None
    for code in codes:
        reply = await session.query(code, args.wait)
        if code == "NRI" and reply is not None and nri_out is not None:
            nri_out.write_text(reply.param, encoding="utf-8")
    await asyncio.sleep(args.linger)
    return 0


async def mode_listen(session: Session, args: argparse.Namespace) -> int:
    session.note(f"listening for {args.duration} s (0 = until stopped)")
    waiter = asyncio.create_task(session.client.wait_closed())
    done, _ = await asyncio.wait({waiter}, timeout=args.duration or None)
    if done:
        session.note(f"connection closed: {session.client.close_reason}")
        return EXIT_CONNECTION
    waiter.cancel()
    return 0


def sweep_codes(alphabet: str, start: str | None, end: str | None) -> Iterator[str]:
    first = [c for c in alphabet if c.isalpha()]
    for chars in itertools.product(first, alphabet, alphabet):
        code = "".join(chars)
        if (start and code < start) or (end and code > end):
            continue
        yield code


async def mode_sweep(session: Session, args: argparse.Namespace) -> int:
    session.rx_tag = "sweep"
    alphabet = args.alphabet.upper()
    codes = list(sweep_codes(alphabet, args.start, args.end))
    session.note(f"sweep of {len(codes)} codes, batch {args.batch}, pause {args.pause} s")
    started = len(session.inbox)
    last = ""
    try:
        for i in range(0, len(codes), args.batch):
            batch = codes[i : i + args.batch]
            for code in batch:
                await session.send(f"{code}QSTN", "sweep")
                last = code
                await asyncio.sleep(args.gap)
            await asyncio.sleep(args.pause)
            if not session.client.connected:
                break
    except ConnectionClosedError:
        pass
    if session.client.connected:
        await asyncio.sleep(args.linger)
    hits = sorted({m.code for m in session.inbox[started:]})
    if not session.client.connected:
        session.note(
            f"connection closed during the sweep after {last}: {session.client.close_reason}; "
            f"resume with --start {last}"
        )
        session.note(f"codes that answered so far: {' '.join(hits)}")
        return EXIT_CONNECTION
    session.note(f"sweep done, last code {last}; codes that answered: {' '.join(hits)}")
    return 0


def check_volume(code: str, param: str, recorded: str, ceiling: str | None) -> None:
    """Refuse a volume set above the recorded level (RULES.md 7, DECISIONS.md #13)."""
    if code not in VOLUME_CODES:
        return
    if not param or not set(param) <= HEX_DIGITS:
        if param.startswith("DOWN"):
            return
        msg = f"volume set {code}{param} is not a plain level (UP and QSTN are refused)"
        raise Refused(msg)
    limit = int(recorded, 16)
    if ceiling is not None:
        limit = min(limit, int(ceiling, 16))
    if int(param, 16) > limit:
        msg = f"volume {param} is above the recorded level {recorded} (ceiling {limit:X})"
        raise Refused(msg)


def restore_message(message: str, query_code: str, before: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    if message.startswith("DSSC"):
        restore = DSS_TO_WRITE.get(before)
        if restore is None:
            msg = f"no Dirac restore for DSS value {before!r}; pass --restore"
            raise Refused(msg)
        return restore
    if message[:3] != query_code:
        msg = f"{message} is read with {query_code}; pass --restore"
        raise Refused(msg)
    return f"{query_code}{before}"


async def write_one(session: Session, message: str, args: argparse.Namespace) -> dict[str, Any]:
    """Record, set, read back, restore and verify one value. Returns the result record."""
    code = message[:3].upper()
    param = message[3:]
    query_code = (args.query or code).upper()
    result: dict[str, Any] = {"set": message, "query": query_code, "restored": False}
    if args.command_only:
        await session.send(message, "set")
        await asyncio.sleep(args.settle)
        result["accepted"] = None
        result["restored"] = None
        return result
    before_msg = await session.query(query_code, args.wait)
    if before_msg is None or before_msg.param == "N/A":
        msg = f"cannot record {query_code} first (reply: {before_msg and before_msg.param!r})"
        raise Refused(msg)
    before = before_msg.param
    result["before"] = before
    check_volume(code, param, before, args.volume_ceiling)
    restore = restore_message(message, query_code, before, args.restore)
    result["restore"] = restore
    session.note(f"write {message}: recorded {query_code}={before}, restore with {restore}")
    set_sent = False
    try:
        mark = len(session.inbox)
        sent_at = time.monotonic()
        set_sent = True
        await session.send(message, "set")
        await asyncio.sleep(args.settle)
        window = session.inbox[mark:]
        reply = next((m for m in window if m.code in {code, query_code}), None)
        result["reply"] = reply.param if reply else None
        result["accepted"] = reply is not None and reply.param != "N/A"
        result["messages"] = [m.raw.rstrip("\x1a\r\n") for m in window]
        result["settle_s"] = round(time.monotonic() - sent_at, 2)
        readback = await session.query(query_code, args.wait)
        result["readback"] = readback.param if readback else None
    finally:
        if set_sent:
            result["restored"] = await restore_and_verify(
                session, restore, query_code, before, args
            )
    return result


async def restore_and_verify(
    session: Session, restore: str, query_code: str, before: str, args: argparse.Namespace
) -> bool:
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(RESTORE_RETRY_DELAY)
        try:
            await session.send(restore, "restore")
            await asyncio.sleep(args.settle)
            after = await session.query(query_code, args.wait)
        except ConnectionClosedError:
            session.note("connection closed before the restore was confirmed")
            return False
        if after is not None and after.param == before:
            return True
    return False


async def mode_write(session: Session, args: argparse.Namespace) -> int:
    status = 0
    for i, message in enumerate(args.messages):
        if i:
            await asyncio.sleep(args.gap)
        try:
            result = await write_one(session, message, args)
        except Refused as err:
            session.note(f"REFUSED {message}: {err}")
            status = max(status, EXIT_REFUSED)
            continue
        session.note("result " + json.dumps(result, ensure_ascii=False))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result["restored"] is False:
            session.note(f"NOT RESTORED: {result['query']} was {result.get('before')}")
            status = EXIT_NOT_RESTORED
            break
    return status


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument(
        "--host", default=os.environ.get("ONKYO_HOST"), help="receiver address (or ONKYO_HOST)"
    )
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--out", required=True, help="capture file (JSONL, appended)")
    p.add_argument("--conn", type=int, default=1, help="connection number written to the log")
    sub = p.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("read", help="query codes")
    r.add_argument("codes", nargs="*", help="three character codes")
    r.add_argument("--codes-file", help="one code per line, # starts a comment")
    r.add_argument("--wait", type=float, default=0.5, help="seconds to wait per reply")
    r.add_argument("--linger", type=float, default=1.0, help="seconds to keep listening at the end")
    r.add_argument("--nri-out", help="write the NRI reply (XML) to this file")

    li = sub.add_parser("listen", help="log pushes only")
    li.add_argument("--duration", type=float, default=60.0, help="seconds, 0 = until stopped")

    s = sub.add_parser("sweep", help="query every three character code")
    s.add_argument("--alphabet", default=string.ascii_uppercase + string.digits)
    s.add_argument("--start", help="first code (resume point)")
    s.add_argument("--end", help="last code")
    s.add_argument("--batch", type=int, default=200)
    s.add_argument("--pause", type=float, default=1.5, help="seconds between batches")
    s.add_argument("--gap", type=float, default=0.002, help="seconds between two sends")
    s.add_argument("--linger", type=float, default=3.0)

    w = sub.add_parser("write", help="record, set, read back, restore, verify")
    w.add_argument("messages", nargs="+", help="full messages, for example MVL3C or DSSC01")
    w.add_argument("--query", help="code that reads the value back (default: first three letters)")
    w.add_argument("--restore", help="message that restores it (default: the recorded value)")
    w.add_argument(
        "--volume-ceiling", help="volume hex level never to exceed (session start level)"
    )
    w.add_argument("--settle", type=float, default=1.5, help="seconds to wait after each send")
    w.add_argument("--wait", type=float, default=1.0, help="seconds to wait for a read reply")
    w.add_argument("--gap", type=float, default=3.5, help="seconds between messages")
    w.add_argument(
        "--command-only",
        action="store_true",
        help="keys with no state (OSD): send once, no record, no restore",
    )
    args = p.parse_args(argv)
    if not args.host:
        p.error("--host (or ONKYO_HOST) is required")
    return args


async def run(args: argparse.Namespace) -> int:
    session = Session(args.host, args.port, Path(args.out), args.conn)
    try:
        await session.open()
    except OSError as err:
        print(f"cannot connect: {err}", file=sys.stderr)
        return EXIT_CONNECTION
    session.note(f"mode {args.mode}")
    modes = {"read": mode_read, "listen": mode_listen, "sweep": mode_sweep, "write": mode_write}
    try:
        status = await modes[args.mode](session, args)
    except Refused as err:
        print(f"refused: {err}", file=sys.stderr)
        status = EXIT_REFUSED
    except ConnectionClosedError as err:
        session.note(f"connection closed: {err}")
        status = EXIT_CONNECTION
    finally:
        await session.close()
    return status


def main() -> int:
    with contextlib.suppress(KeyboardInterrupt):
        return asyncio.run(run(parse_args()))
    return 130


if __name__ == "__main__":
    sys.exit(main())
