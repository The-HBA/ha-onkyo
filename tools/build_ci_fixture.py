"""Write the CI part of a simulator fixture (``ci.json``) from a private capture session.

    python tools/build_ci_fixture.py <session.jsonl> <fixture folder>

Reads every CI record (lower-case ``s`` code) the receiver sent in a session that read the whole
config, keeps each distinct record, hides the network address, the MAC and the
friendly name, and writes ``ci.json``: ``{"records": [...], "ignored": [...]}``. The simulator
(tools/eiscp_sim) answers CI reads from it and applies partial sets to it.
"""

import argparse
import json
import sys
from pathlib import Path

PLACEHOLDER_NETWORK = (
    "sNTCNT000MA0009B0000001 DH001IP00000000SNFFFFFF00GW00000000DS00000000PU"
    + " " * 128
    + "PP1F90    "
)
PLACEHOLDER_NAME = (
    "sN2CFNOnkyo Receiver" + " " * 13 + "AS001AP" + " " * 33 + "ANOnkyo Receiver" + " " * 13
)
EXTRA = ("sSWCF1063L1000F2125L2000F3250L3000",)
"""Records the capture session did not read but another session did (specs/web-setup-backup.md)."""
IGNORED_FAMILIES = ["CFC", "LLC", "TNC", "VIC"]
"""Families whose sets the real receiver ignores (record unchanged, no reply)."""
NO_STATE = ("sST-", "sAM-")
"""Live state records: not config, left out."""


def records(session: Path) -> list[str]:
    found: dict[str, str] = {}
    for line in session.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        raw = row.get("raw", "")
        if row.get("dir") != "rx" or not raw.startswith("!1s"):
            continue
        text = raw[2:].rstrip("\x1a\r\n")
        if text.startswith(NO_STATE):
            continue
        if text.startswith("sNTC"):
            text = PLACEHOLDER_NETWORK
        elif text.startswith("sN2C"):
            text = PLACEHOLDER_NAME
        found.setdefault(text, text)
    return [*found.values(), *EXTRA]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    parser.add_argument("session", type=Path, help="private capture session (jsonl)")
    parser.add_argument("out", type=Path, help="fixture folder, for example tests/fixtures/tx-rz50")
    args = parser.parse_args(argv)
    data = {"records": records(args.session), "ignored": IGNORED_FAMILIES}
    (args.out / "ci.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(f"{len(data['records'])} records\n")


if __name__ == "__main__":
    main()
