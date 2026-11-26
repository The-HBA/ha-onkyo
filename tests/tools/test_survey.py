"""The survey tool against a tiny fake receiver (never the real one)."""

import argparse
import asyncio
import json
import string
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from custom_components.onkyo_eiscp.lib import FrameParser
from tools import eiscp_survey as survey


def reply_packet(message: str) -> bytes:
    data = f"!1{message}\x1a\r\n".encode("latin-1")
    return b"ISCP" + (16).to_bytes(4, "big") + len(data).to_bytes(4, "big") + b"\x01\0\0\0" + data


class FakeReceiver:
    def __init__(self) -> None:
        self.state = {"MVL": "3C", "SLI": "11", "DSS": "211"}
        self.received: list[str] = []
        self.refuse = {"SLI": {"FF"}}
        self.server: asyncio.Server | None = None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        parser = FrameParser()
        while data := await reader.read(4096):
            for message in parser.feed(data):
                text = message.code + message.param
                self.received.append(text)
                for reply in self.answer(message.code, message.param):
                    writer.write(reply_packet(reply))
                await writer.drain()

    def answer(self, code: str, param: str) -> list[str]:
        if code == "DSS" and param.startswith("C"):
            slots = {"00": "111", "01": "211", "02": "121", "03": "112"}
            self.state["DSS"] = slots[param[1:]]
            return ["DSS" + self.state["DSS"]]
        if code not in self.state:
            return []
        if param == "QSTN":
            return [code + self.state[code]]
        if param in self.refuse.get(code, set()):
            return [code + "N/A"]
        self.state[code] = param
        return [code + param]


@pytest.fixture
async def receiver() -> AsyncIterator[tuple[FakeReceiver, int]]:
    fake = FakeReceiver()
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield fake, port
    server.close()
    await server.wait_closed()


def make_args(tmp_path: Path, port: int, *argv: str) -> argparse.Namespace:
    return survey.parse_args(
        ["--host", "127.0.0.1", "--port", str(port), "--out", str(tmp_path / "c.jsonl"), *argv]
    )


def result_text(tmp_path: Path) -> str:
    texts = [r.get("text", "") for r in records(tmp_path)]
    return next(t for t in texts if t.startswith("result ")).removeprefix("result ")


def records(tmp_path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in (tmp_path / "c.jsonl").read_text().splitlines()]


async def test_read_logs_c1_records_and_only_sends_qstn(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "read", "MVL", "SLI", "ZZZ", "--wait", "0.1", "--linger", "0")
    assert await survey.run(args) == 0
    assert fake.received == ["MVLQSTN", "SLIQSTN", "ZZZQSTN"]
    recs = [r for r in records(tmp_path) if r["tag"] != "note"]
    assert [(r["dir"], r["code"], r["param"], r["tag"]) for r in recs] == [
        ("tx", "MVL", "QSTN", "query"),
        ("rx", "MVL", "3C", "reply"),
        ("tx", "SLI", "QSTN", "query"),
        ("rx", "SLI", "11", "reply"),
        ("tx", "ZZZ", "QSTN", "query"),
    ]
    assert recs[1]["raw"] == "!1MVL3C\x1a\r\n"


async def test_read_refuses_codes_with_parameters(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    assert await survey.run(make_args(tmp_path, port, "read", "MVL3D")) == survey.EXIT_REFUSED
    assert fake.received == []


async def test_write_records_sets_and_restores(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "write", "SLI05", "--settle", "0.05", "--wait", "0.2")
    assert await survey.run(args) == 0
    assert fake.received == ["SLIQSTN", "SLI05", "SLIQSTN", "SLI11", "SLIQSTN"]
    assert fake.state["SLI"] == "11"
    result = json.loads(result_text(tmp_path))
    assert result["before"] == "11"
    assert result["accepted"] is True
    assert result["readback"] == "05"
    assert result["restored"] is True


async def test_write_refused_set_is_restored_and_reported(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "write", "SLIFF", "--settle", "0.05", "--wait", "0.2")
    assert await survey.run(args) == 0
    assert fake.state["SLI"] == "11"
    assert any('"accepted": false' in r["text"] for r in records(tmp_path) if r.get("text"))


async def test_dirac_write_restores_through_the_write_code(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "write", "DSSC03", "--settle", "0.05", "--wait", "0.2")
    assert await survey.run(args) == 0
    assert fake.received == ["DSSQSTN", "DSSC03", "DSSQSTN", "DSSC01", "DSSQSTN"]
    assert fake.state["DSS"] == "211"


async def test_volume_above_recorded_level_is_refused_before_any_write(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    for target in ("MVL3D", "MVLUP", "MVLQSTN"):
        args = make_args(tmp_path, port, "write", target, "--settle", "0.05", "--wait", "0.2")
        assert await survey.run(args) == survey.EXIT_REFUSED
    assert fake.received.count("MVL3D") == 0
    assert "MVLUP" not in fake.received
    assert fake.state["MVL"] == "3C"


async def test_volume_down_and_ceiling(receiver: tuple[FakeReceiver, int], tmp_path: Path) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "write", "MVL3A", "--settle", "0.05", "--wait", "0.2")
    assert await survey.run(args) == 0
    assert fake.state["MVL"] == "3C"
    args = make_args(tmp_path, port, "write", "MVL3A", "--volume-ceiling", "30", "--settle", "0.05")
    assert await survey.run(args) == survey.EXIT_REFUSED


async def test_write_refuses_when_value_cannot_be_recorded(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "write", "ZZZ01", "--settle", "0.05", "--wait", "0.1")
    assert await survey.run(args) == survey.EXIT_REFUSED
    assert fake.received == ["ZZZQSTN"]


async def test_sweep_batches_and_lists_hits(
    receiver: tuple[FakeReceiver, int], tmp_path: Path
) -> None:
    fake, port = receiver
    args = make_args(
        tmp_path, port, "sweep", "--start", "DSA", "--end", "DSZ",
        "--alphabet", string.ascii_uppercase,
        "--batch", "10", "--pause", "0.02", "--gap", "0", "--linger", "0.1",
    )  # fmt: skip
    assert await survey.run(args) == 0
    assert len(fake.received) == 26
    assert all(m.endswith("QSTN") for m in fake.received)
    notes = [r["text"] for r in records(tmp_path) if r["tag"] == "note"]
    assert any("answered: DSS" in n for n in notes)


async def test_listen_logs_pushes(receiver: tuple[FakeReceiver, int], tmp_path: Path) -> None:
    fake, port = receiver
    args = make_args(tmp_path, port, "listen", "--duration", "0.3")
    assert await survey.run(args) == 0
    assert fake.received == []
