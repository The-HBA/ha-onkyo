"""The CI fixture builder keeps config records and hides the network details."""

import json
from pathlib import Path

from tools import build_ci_fixture


def _row(raw: str) -> str:
    return json.dumps({"dir": "rx", "raw": "!1" + raw + "\x1a\r\n"})


def test_builder_hides_network_and_keeps_config(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    lines = [
        _row("sAPCST000AP000HT000PO001NS001WU000"),
        _row("sAPCST000AP000HT000PO001NS001WU000"),
        _row("sNTCNT000MA0009B0AAAAAA DH001IPC0A80002SNFFFFFF00GWC0A80001"),
        _row("sN2CFNMy Own Name"),
        _row("sST-PM001"),
        json.dumps({"dir": "tx", "raw": "!1sAPCQSTN\r"}),
    ]
    session.write_text("\n".join(lines), encoding="utf-8")
    out = tmp_path / "fixture"
    out.mkdir()
    build_ci_fixture.main([str(session), str(out)])
    data = json.loads((out / "ci.json").read_text(encoding="utf-8"))
    text = json.dumps(data)
    assert text.count("sAPC") == 1
    assert "C0A80002" not in text
    assert "B0AAAAAA" not in text
    assert "My Own Name" not in text
    assert "sST-" not in text
    assert "CFC" in data["ignored"]
