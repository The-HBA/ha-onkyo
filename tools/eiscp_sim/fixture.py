"""Load a simulator fixture folder (written by ``tools/sanitize_capture.py``)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

RELATIVE_PARAMS = frozenset({"UP", "DOWN", "UP1", "DOWN1", "MUSIC", "TG"})
# Kinds that say what the receiver did whatever the state was before the write.
STATE_FREE_KINDS = frozenset({"changed", "refused", "refused_push", "command", "silent"})
ACCEPTED_KINDS = frozenset({"changed", "same", "same_silent"})
SELECTOR = re.compile(r'<selector id="([0-9A-Fa-f]+)" value="(\d+)" name="([^"]*)"')


@dataclass(frozen=True, slots=True)
class Write:
    """One write the survey tried on the real receiver."""

    code: str
    param: str
    kind: str
    before: str | None
    reply: str | None
    readback: str | None
    pushes: tuple[str, ...]


@dataclass(slots=True)
class Fixture:
    """Everything the simulator knows about one receiver model."""

    profile: dict[str, Any]
    on: dict[str, str]
    standby: dict[str, str | None]
    writes: dict[tuple[str, str], list[Write]]
    nri: str
    behavior: dict[str, Any]
    inputs: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, folder: Path) -> Fixture:
        """Read the five fixture files (profile, state, writes, behavior, nri) from ``folder``."""
        profile = _read(folder / "profile.json")
        state = _read(folder / "state.json")
        writes: dict[tuple[str, str], list[Write]] = {}
        behavior = _read(folder / "behavior.json")
        skip = set(behavior.get("context_sessions", []))
        for item in _read(folder / "writes.json"):
            if item.get("session") in skip:
                continue  # taken on another input or in another state; ranges cover them
            write = Write(
                code=item["code"],
                param=item["param"],
                kind=item["kind"],
                before=item.get("before"),
                reply=item.get("reply"),
                readback=item.get("readback"),
                pushes=tuple(item.get("pushes", [])),
            )
            writes.setdefault((write.code, write.param), []).append(write)
        nri = (folder / "nri.xml").read_text(encoding="utf-8")
        inputs = {sid.upper(): name for sid, value, name in SELECTOR.findall(nri) if int(value) > 0}
        return cls(
            profile=profile,
            on=state["on"],
            standby=state["standby"],
            writes=writes,
            nri=nri,
            behavior=behavior,
            inputs=inputs,
        )

    def accepted_params(self, code: str) -> set[str]:
        """Values a set may carry: the recorded accepted params plus the values seen in states."""
        found = {
            write.param
            for (wcode, _), items in self.writes.items()
            if wcode == code
            for write in items
            if write.kind in ACCEPTED_KINDS and write.param not in RELATIVE_PARAMS
        }
        if code in self.on:
            found.add(self.on[code])
        found.update(v for c, v in self.standby.items() if c == code and v is not None)
        return found

    def kinds(self, code: str) -> set[str]:
        """The kinds of every recorded write of ``code``."""
        return {w.kind for (wcode, _), items in self.writes.items() if wcode == code for w in items}


def _read(path: Path) -> Any:  # noqa: ANN401
    return json.loads(path.read_text(encoding="utf-8"))
