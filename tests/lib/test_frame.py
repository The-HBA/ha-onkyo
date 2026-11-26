import pytest

from custom_components.onkyo_eiscp.lib import FrameError, FrameParser, encode, parse_data


def packet(data: bytes) -> bytes:
    return (
        b"ISCP"
        + (16).to_bytes(4, "big")
        + len(data).to_bytes(4, "big")
        + b"\x01\x00\x00\x00"
        + data
    )


def test_encode_matches_wire_format() -> None:
    assert encode("PWRQSTN") == packet(b"!1PWRQSTN\r")
    assert encode("MVLQSTN", unit="x") == packet(b"!xMVLQSTN\r")


@pytest.mark.parametrize("end", ["", "\r", "\n", "\r\n", "\x1a", "\x1a\r", "\x1a\r\n"])
def test_end_bytes_are_tolerated(end: str) -> None:
    (message,) = FrameParser().feed(packet(f"!1MVL7C{end}".encode("latin-1")))
    assert (message.unit, message.code, message.param) == ("1", "MVL", "7C")
    assert message.raw == f"!1MVL7C{end}"


def test_parameter_may_be_empty_or_hold_end_bytes_inside() -> None:
    (message,) = FrameParser().feed(packet(b"!1FLD\r\n"))
    assert (message.code, message.param) == ("FLD", "")
    (message,) = FrameParser().feed(packet(b"!1NRI<a>\r\n</a>\x1a\r\n"))
    assert message.param == "<a>\r\n</a>"


def test_split_packets_at_every_byte() -> None:
    stream = packet(b"!1PWR01\x1a\r\n") + packet(b"!1SLI11\x1a\r\n")
    parser = FrameParser()
    messages = []
    for i in range(len(stream)):
        messages += parser.feed(stream[i : i + 1])
    assert [(m.code, m.param) for m in messages] == [("PWR", "01"), ("SLI", "11")]


def test_two_packets_in_one_chunk_and_a_partial_third() -> None:
    parser = FrameParser()
    third = packet(b"!1AMT00\x1a\r\n")
    chunk = packet(b"!1PWR01\r") + packet(b"!1MVL3D\r") + third[:10]
    assert [m.code for m in parser.feed(chunk)] == ["PWR", "MVL"]
    assert [m.code for m in parser.feed(third[10:])] == ["AMT"]


def test_large_reply_like_nri() -> None:
    xml = '<?xml version="1.0"?>' + "<x>a</x>" * 1500
    (message,) = FrameParser().feed(packet(f"!1NRI{xml}\x1a\r\n".encode("latin-1")))
    assert message.param == xml


def test_longer_header_is_skipped() -> None:
    data = b"!1PWR01\x1a\r\n"
    raw = (
        b"ISCP"
        + (20).to_bytes(4, "big")
        + len(data).to_bytes(4, "big")
        + b"\x01\0\0\0"
        + b"EXTR"
        + data
    )
    (message,) = FrameParser().feed(raw)
    assert message.code == "PWR"


def test_bad_magic_and_bad_data_raise() -> None:
    with pytest.raises(FrameError):
        FrameParser().feed(b"HTTP/1.1 200 OK\r\n\r\n")
    with pytest.raises(FrameError):
        FrameParser().feed(packet(b"garbage"))
    with pytest.raises(FrameError):
        parse_data("!1PW")
