"""Turn a private capture folder into a public simulator fixture.

    python tools/sanitize_capture.py captures/2026-11-26-tx-rz50 tests/fixtures/tx-rz50

Input (see ARCHITECTURE.md C1): ``survey.json``, ``nri.xml`` and the sessions folder of one
day and model. Output (read by ``tools/eiscp_sim``):

- ``profile.json``: model, firmware, placeholder identity, power-on and power-off pushes.
- ``state.json``: what each code answered on (start of the survey) and in standby.
- ``writes.json``: every write the survey tried: reply, read back, pushes, kind.
- ``nri.xml``: the NRI reply with the identity replaced.

``behavior.json`` (listening modes, signals, ranges) is written by hand, is not private and is
never overwritten. The private values (MAC, friendly name, IP address) are found in the capture
itself, replaced, and the result is checked again before anything is written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PLACEHOLDER_MAC = "0009B0000001"
PLACEHOLDER_NAME = "Onkyo Test"
PLACEHOLDER_HOST = "receiver.invalid"
PLACEHOLDER_ZONE = "Etc/UTC"
IP_PATTERN = re.compile(r"\d{1,3}(?:\. ?\d{1,3}){3}")
NOT_READ = "not read"
# Codes that arrive after a power-on but are not part of the settings burst.
BURST_SKIP = frozenset({"NJA", "NLS", "UPD", "NRI", "NSB", "NLT", "NCP"})
KINDS = (
    ("refused (pushes", "refused_push"),
    ("refused", "refused"),
    ("changed", "changed"),
    ("same value (no reply)", "same_silent"),
    ("same value", "same"),
    ("silent", "silent"),
    ("ignored", "ignored"),
    ("command", "command"),
)


class Scrubber:
    """Replace the private values found in a capture with fixed placeholders."""

    def __init__(self, nri_xml: str, codes: dict[str, Any]) -> None:
        """Collect the MAC, the friendly names and the addresses to hide."""
        self.macs: set[str] = set()
        self.names: set[str] = set()
        for tag in ("macaddress", "deviceserial"):
            match = re.search(rf"<{tag}>([0-9A-Fa-f]{{12}})</{tag}>", nri_xml)
            if match:
                self.macs.add(match.group(1).upper())
        match = re.search(r"<friendlyname>([^<]+)</friendlyname>", nri_xml)
        if match:
            self.names.add(match.group(1))
        nfn = codes.get("NFN", {}).get("states", {}).get("on")
        if isinstance(nfn, str):
            self.names.add(nfn.lstrip("."))
        ifn = codes.get("IFN", {}).get("states", {}).get("on")
        if isinstance(ifn, str) and ifn.count(",") >= 2:  # noqa: PLR2004
            self.names.add(ifn.split(",", 2)[2])
        self.names.discard("")

    def text(self, value: str) -> str:
        """Return ``value`` with every private value replaced."""
        for mac in self.macs:
            colon = ":".join(mac[i : i + 2] for i in range(0, 12, 2))
            value = re.sub(re.escape(colon), _colon(PLACEHOLDER_MAC), value, flags=re.IGNORECASE)
            value = re.sub(re.escape(mac), PLACEHOLDER_MAC, value, flags=re.IGNORECASE)
        value = IP_PATTERN.sub(PLACEHOLDER_HOST, value)
        for name in sorted(self.names, key=len, reverse=True):
            value = value.replace(name, PLACEHOLDER_NAME)
        return value

    def tree(self, value: Any) -> Any:  # noqa: ANN401
        """Scrub every string in a JSON-like structure."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.tree(item) for item in value]
        if isinstance(value, dict):
            return {key: self.tree(item) for key, item in value.items()}
        return value

    def leftovers(self, value: str) -> list[str]:
        """Return the private values still present in ``value`` (should be empty)."""
        found = [mac for mac in self.macs if mac.lower() in value.lower()]
        found += [name for name in self.names if name in value]
        found += IP_PATTERN.findall(value)
        return found


def _colon(mac: str) -> str:
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2))


def classify(outcome: str | None) -> str | None:
    """Map the survey's outcome text to a short kind."""
    if outcome is None:
        return None
    for prefix, kind in KINDS:
        if outcome.startswith(prefix):
            return kind
    return "other"


def split_message(raw: str) -> tuple[str, str]:
    """Split ``CODEPARAM`` (a push or reply without the ``!1`` prefix) into code and param."""
    return raw[:3], raw[3:]


def read_session(path: Path) -> list[dict[str, Any]]:
    """Read one capture session (JSON lines)."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def messages_after(
    rows: list[dict[str, Any]], raw_set: str, seconds: float
) -> list[tuple[str, str]]:
    """Return the pushes seen up to ``seconds`` after the first send of ``raw_set``."""
    from datetime import datetime  # noqa: PLC0415

    def when(row: dict[str, Any]) -> float:
        return datetime.fromisoformat(row["ts"]).timestamp()

    start = next(
        (row for row in rows if row["tag"] in {"set", "restore"} and row["raw"] == raw_set), None
    )
    if start is None:
        return []
    found: list[tuple[str, str]] = []
    for row in rows:
        if row["dir"] != "rx" or row["tag"] != "push":
            continue
        if 0 <= when(row) - when(start) <= seconds:
            found.append((row["code"], row["param"].rstrip("\x1a\r\n")))
    return found


def build_state(codes: dict[str, Any]) -> dict[str, Any]:
    """The start-of-survey answer per code, and the standby differences."""
    on: dict[str, str] = {}
    standby: dict[str, str | None] = {}
    for code, entry in sorted(codes.items()):
        states = entry.get("states", {})
        candidates = (entry.get("start_p1s3"), entry.get("start"), states.get("on"))
        start = next((c for c in candidates if isinstance(c, str) and c != NOT_READ), None)
        if start is None:
            continue
        on[code] = start
        sb = states.get("standby", NOT_READ)
        if sb == NOT_READ:
            continue
        if sb != start:
            standby[code] = sb
    return {"on": on, "standby": standby}


def build_writes(codes: dict[str, Any], capture: Path | None = None) -> list[dict[str, Any]]:
    """One entry per write the survey classified; the rest are notes about the tool.

    A refused set that pushes the answer (zone 3 power-on) has no ``also`` list in the survey,
    so its pushes are read from the session file (the first 0.5 s after the set).
    """
    writes: list[dict[str, Any]] = []
    for code, entry in sorted(codes.items()):
        for write in entry.get("writes", []):
            kind = classify(write.get("outcome"))
            if kind is None:
                continue
            item = {
                "code": code,
                "param": write["param"],
                "kind": kind,
                "before": write.get("before"),
                "reply": write.get("reply"),
                "readback": write.get("readback"),
                "pushes": write.get("also", []),
            }
            if kind == "refused_push" and capture is not None and "session" in write:
                rows = read_session(capture / write["session"])
                found = messages_after(rows, f"!1{write['set']}\r", 0.5)
                item["pushes"] = [c + p for c, p in found if c != "NJA"]
                item["reply"] = None
            writes.append(item)
    return writes


def build_profile(
    survey: dict[str, Any], rows_power: list[dict[str, Any]], state: dict[str, Any]
) -> dict[str, Any]:
    """Model facts plus what the receiver pushes around a power change."""
    burst: list[str] = []
    push_only: dict[str, str] = {}
    for code, param in messages_after(rows_power, "!1PWR01\r", 12.0):
        if code in BURST_SKIP:
            continue
        if code not in burst:
            burst.append(code)
        if code not in state["on"] and code != "FLD":
            push_only.setdefault(code, param)
    off = [
        code + param
        for code, param in messages_after(rows_power, "!1PWR00\r", 3.0)
        if code not in BURST_SKIP and code != "PWR"
    ]
    connect = next((row for row in rows_power if row["dir"] == "rx" and row["code"] == "NJA"), None)
    mvl_on = survey["codes"]["MVL"]["states"]["on"]
    return {
        "model": survey["model"],
        "firmware": survey["firmware"],
        "fwv_reply": survey["fwv_reply"],
        "captured": survey["captured"],
        "mac": PLACEHOLDER_MAC,
        "friendly_name": PLACEHOLDER_NAME,
        "mode_lock_seconds": 3.0,
        "power_on_volume": mvl_on,
        "power_on_burst": burst,
        "power_on_only": push_only,
        "power_off_pushes": off,
        "connect_push": [connect["code"] + connect["param"].rstrip("\x1a\r\n")] if connect else [],
    }


def sanitize(capture: Path, out: Path) -> None:
    """Write the fixture for ``capture`` into ``out``."""
    survey = json.loads((capture / "survey.json").read_text(encoding="utf-8"))
    nri_xml = (capture / "nri.xml").read_text(encoding="utf-8")
    scrub = Scrubber(nri_xml, survey["codes"])
    state = build_state(survey["codes"])
    rows = read_session(capture / "session-10-power-cycle.jsonl")
    files: dict[str, str] = {
        "profile.json": _dump(build_profile(survey, rows, state)),
        "state.json": _dump(state),
        "writes.json": _dump(build_writes(survey["codes"], capture)),
        "nri.xml": nri_xml,
    }
    result = {
        name: scrub.text(text) if name == "nri.xml" else _scrub_json(scrub, text)
        for name, text in files.items()
    }
    for name, text in result.items():
        left = scrub.leftovers(text)
        if left:
            sys.exit(f"{name} still holds private values; stopping before writing ({len(left)})")
    out.mkdir(parents=True, exist_ok=True)
    for name, text in result.items():
        (out / name).write_text(text, encoding="utf-8")


def _scrub_json(scrub: Scrubber, text: str) -> str:
    data = scrub.tree(json.loads(text))
    zone = data.get("on", {}) if isinstance(data, dict) else {}
    if isinstance(zone, dict) and "NGT" in zone:
        zone["NGT"] = PLACEHOLDER_ZONE
    return _dump(data)


def _dump(data: Any) -> str:  # noqa: ANN401
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    """Command line entry."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    parser.add_argument("capture", type=Path, help="private capture folder")
    parser.add_argument("out", type=Path, help="fixture folder, for example tests/fixtures/tx-rz50")
    args = parser.parse_args(argv)
    sanitize(args.capture, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
