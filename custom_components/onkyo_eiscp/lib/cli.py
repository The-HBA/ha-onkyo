"""Command line for manual tests from a laptop (read only).

    python -m custom_components.onkyo_eiscp.lib discover [--host ADDRESS]
    python -m custom_components.onkyo_eiscp.lib info --host ADDRESS
    python -m custom_components.onkyo_eiscp.lib read --host ADDRESS [CODE ...]
    python -m custom_components.onkyo_eiscp.lib listen --host ADDRESS [--seconds 30]

It never sets anything. One connection per run: the receiver closes an older connection from
the same computer, so stop other tools first.
"""

# ruff: noqa: T201  (a command line tool prints)

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Any

from .codecs import decode
from .commands import COMMANDS
from .discovery import DEFAULT_PORT, discover
from .exceptions import CodecError, EiscpError
from .receiver import Receiver

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence

DEFAULT_CODES = ("PWR", "MVL", "AMT", "SLI", "LMD", "DSS", "IFA", "IFV", "FLD")


def _show(code: str, param: str) -> str:
    command = COMMANDS.get(code)
    if command is None or param == "N/A":
        return f"{code} {param}"
    try:
        return f"{code} {param}  ->  {decode(command, param)}"
    except CodecError:
        return f"{code} {param}"


async def _discover(args: argparse.Namespace) -> int:
    found = await discover(args.host, args.timeout, port=args.port)
    for item in found:
        print(f"{item.host}:{item.port}  {item.model}  {item.mac}")
    if not found:
        print("no receiver answered", file=sys.stderr)
    return 0 if found else 1


async def _info(args: argparse.Namespace) -> int:
    receiver = Receiver(args.host, args.port, restore_volume=False)
    capabilities = await receiver.start()
    try:
        print(f"{capabilities.brand} {capabilities.model}  firmware {capabilities.firmware}")
        print("zones:", ", ".join(f"{z.id} ({z.name})" for z in capabilities.zones))
        print("inputs:")
        for item in capabilities.inputs:
            print(f"  {item.code}  {item.name}  {sorted(item.zones)}")
        print(f"supported codes ({len(capabilities.supported)}):", *sorted(capabilities.supported))
        print("unavailable now:", *sorted(receiver.unavailable))
    finally:
        await receiver.stop()
    return 0


async def _read(args: argparse.Namespace) -> int:
    receiver = Receiver(args.host, args.port, restore_volume=False)
    await receiver.start()
    try:
        for code in args.codes or DEFAULT_CODES:
            try:
                print(_show(code.upper(), await receiver.query(code.upper())))
            except (EiscpError, ValueError) as err:
                print(f"{code.upper()} {err}")
    finally:
        await receiver.stop()
    return 0


async def _listen(args: argparse.Namespace) -> int:
    receiver = Receiver(args.host, args.port, restore_volume=False)
    await receiver.start()
    try:
        seen: set[str] = set()
        receiver.add_listener(seen.update)
        deadline = asyncio.get_running_loop().time() + args.seconds
        reported: dict[str, str] = dict(receiver.values)
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.2)
            for code in sorted(seen):
                value = receiver.values.get(code)
                if value is not None and reported.get(code) != value:
                    reported[code] = value
                    print(_show(code, value))
            seen.clear()
    finally:
        await receiver.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; returns the exit code."""
    parser = argparse.ArgumentParser(prog="onkyo_eiscp.lib", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add(
        name: str,
        handler: Callable[[argparse.Namespace], Coroutine[Any, Any, int]],
        *,
        host_required: bool,
    ) -> argparse.ArgumentParser:
        item = sub.add_parser(name)
        item.add_argument("--host", required=host_required)
        item.add_argument("--port", type=int, default=DEFAULT_PORT)
        item.set_defaults(handler=handler)
        return item

    found = add("discover", _discover, host_required=False)
    found.add_argument("--timeout", type=float, default=2.0)
    add("info", _info, host_required=True)
    reader = add("read", _read, host_required=True)
    reader.add_argument("codes", nargs="*", help="three letter codes, for example MVL PWR")
    listener = add("listen", _listen, host_required=True)
    listener.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        return int(asyncio.run(args.handler(args)))
    except EiscpError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
