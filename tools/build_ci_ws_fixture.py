"""Build tests/frontend/ci-ws.json: what the CI websocket commands answer, for the browser tests.

The fake Home Assistant in tests/frontend plays the receiver from this file (the same records
as tests/fixtures/tx-rz50/ci.json, split into fields). Run from the repository root:

    .venv/bin/python tools/build_ci_ws_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from custom_components.onkyo_eiscp.ci_api import STATUS_FAMILIES, _describe, _keys
from custom_components.onkyo_eiscp.lib import ci

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tests" / "fixtures" / "tx-rz50" / "ci.json"
TARGET = ROOT / "tests" / "frontend" / "ci-ws.json"


def main() -> None:
    raw = json.loads(SOURCE.read_text())
    caps: Any = SimpleNamespace(
        zones=[SimpleNamespace(id=zone) for zone in ("main", "zone2", "zone3")]
    )
    families = [
        _describe(spec, caps) for code, spec in ci.FAMILIES.items() if code not in STATUS_FAMILIES
    ]
    records: dict[str, list[dict[str, object]]] = {}
    for message in raw["records"]:
        record = ci.decode(message)
        if record.code in STATUS_FAMILIES or record.code not in ci.FAMILIES:
            continue
        spec = ci.FAMILIES[record.code]
        if record.code == "MZC" and record.key.get("ZN") not in {
            k["ZN"] for k in _keys(spec, caps)
        }:
            continue
        records.setdefault(record.code, []).append({"key": record.key, "fields": record.fields})
    TARGET.write_text(json.dumps({"families": families, "records": records}, indent=1) + "\n")


if __name__ == "__main__":
    main()
