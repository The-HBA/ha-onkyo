"""The receiver model: state, answers and side effects. No network and no clock of its own.

``Receiver.handle(code, param)`` returns a ``Result``: ``replies`` go only to the connection
that asked, ``broadcast`` goes to every open connection (the real receiver pushes every change
to every client). The behaviour follows ARCHITECTURE.md C2 and the capture of 2026-11-26.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .fixture import RELATIVE_PARAMS, STATE_FREE_KINDS, Fixture, Write

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

NA = "N/A"
# Codes whose text is computed or transient, so a push never becomes stored state.
NO_STATE = frozenset({"FLD", "IFA", "IFV", "NLS", "NJA", "UPD", "NRI", "NCP", "NLT", "PWR"})
DIMENSION = 14  # characters on the front display


@dataclass(slots=True)
class Result:
    """What one message from a client causes."""

    replies: list[str] = field(default_factory=list)
    broadcast: list[str] = field(default_factory=list)


def silent() -> Result:
    """No reply and no push (the receiver ignores the message)."""
    return Result()


def refuse(code: str) -> Result:
    """A refused set: ``<code>N/A`` to the asker only."""
    return Result(replies=[code + NA])


class Receiver:
    """One simulated receiver, built from a fixture folder."""

    def __init__(self, fixture: Fixture, clock: Callable[[], float] = time.monotonic) -> None:
        """Start in the state the survey began in (powered on, source playing)."""
        self.fixture = fixture
        self.clock = clock
        behavior = fixture.behavior
        self.values: dict[str, str] = dict(fixture.on)
        self.powered = self.values.get("PWR", "01") == "01"
        self.signal: str = behavior["start_signal"]
        self.input_modes: dict[str, str] = {self.values["SLI"]: self.values["LMD"]}
        self.last_mode_change: float | None = None

    @classmethod
    def from_folder(cls, folder: Path, clock: Callable[[], float] = time.monotonic) -> Receiver:
        """Load ``folder`` (for example ``tests/fixtures/tx-rz50``) and start a receiver."""
        return cls(Fixture.load(folder), clock)

    # ----- what a new connection sees -------------------------------------------------------

    def connect_messages(self) -> list[str]:
        """Pushed to a new connection before any reply (the TX-RZ50 sends ``NJA``)."""
        return list(self.fixture.profile.get("connect_push", []))

    # ----- entry point ----------------------------------------------------------------------

    def handle(self, code: str, param: str) -> Result:
        """Answer one message."""
        if param == "QSTN":
            value = self._answer(code)
            return Result(replies=[] if value is None else [code + value])
        return self._set(code, param)

    def set_signal(self, name: str) -> Result:
        """Change the incoming signal (for tests); pushes the new IFA, IFV and a mode if needed."""
        signals = self.fixture.behavior["signals"]
        if name not in signals:
            msg = f"unknown signal {name!r}; choose from {sorted(signals)}"
            raise ValueError(msg)
        self.signal = name
        messages: list[str] = []
        spec = signals[name]
        if self.values["LMD"] not in spec["modes"]:
            self._mark_mode(spec["default_mode"])
            messages.append("LMD" + self.values["LMD"])
        messages += ["IFA" + self._ifa(), "IFV" + self._ifv()]
        return Result(broadcast=messages) if self.powered else silent()

    # ----- queries --------------------------------------------------------------------------

    def _answer(self, code: str) -> str | None:
        if not self.powered and code in self.fixture.standby:
            return self.fixture.standby[code]
        if code == "FLD":
            return self._display()
        if code == "IFA":
            return self._ifa()
        if code == "IFV":
            return self._ifv()
        if code == "NRI":
            return self.fixture.nri
        return self.values.get(code)

    def _display(self) -> str:
        name = self.fixture.inputs.get(self.values["SLI"].upper(), "")
        db = int(self.values["MVL"], 16) / 2 - 82
        return f"{name[:9]:<9}{db:>5.1f}"[:DIMENSION].encode("latin-1").hex().upper()

    def _ifa(self) -> str:
        spec = self.fixture.behavior["signals"][self.signal]
        mode = self.values["LMD"]
        name = spec["names"].get(mode) or self.fixture.behavior["mode_names"].get(mode, mode)
        output = self.fixture.behavior["mode_output"].get(
            mode, self.fixture.behavior["default_output"]
        )
        return str(spec["ifa"]).format(mode=name, output=output)

    def _ifv(self) -> str:
        return self.fixture.on["IFV"]

    # ----- sets -----------------------------------------------------------------------------

    def _set(self, code: str, param: str) -> Result:  # noqa: PLR0911
        if code == "PWR":
            return self._power(param)
        if not self.powered:
            hidden = code in self.fixture.standby and self.fixture.standby[code] is None
            return silent() if hidden or code not in self.fixture.on else refuse(code)
        ranges = self.fixture.behavior["ranges"]
        if code == "LMD":
            return self._lmd(param)
        if code == "SLI":
            return self._sli(param)
        if code == "SLP":
            return self._sleep(param)
        if code in ranges:
            return self._ranged(code, param)
        return self._generic(code, param)

    def _power(self, param: str) -> Result:
        if param not in {"00", "01", "TG"}:
            return refuse("PWR")
        want_on = (not self.powered) if param == "TG" else param == "01"
        if want_on == self.powered:
            return Result(broadcast=["PWR" + ("01" if want_on else "00")])
        self.powered = want_on
        profile = self.fixture.profile
        if not want_on:
            self.values["PWR"] = "00"
            pushes = list(profile.get("power_off_pushes", []))
            self._apply(pushes)
            return Result(broadcast=["PWR00", *pushes])
        self.values["PWR"] = "01"
        for code, value in self.fixture.on.items():
            if code in self.fixture.standby and self.fixture.standby[code] is not None:
                self.values[code] = value  # follows power (TGA, TPD)
        self.values["MVL"] = profile["power_on_volume"]
        self._mark_mode(self.values["LMD"])
        return Result(broadcast=self._burst())

    def _burst(self) -> list[str]:
        only = self.fixture.profile.get("power_on_only", {})
        messages: list[str] = []
        for code in self.fixture.profile.get("power_on_burst", []):
            if code == "PWR":
                messages.append("PWR01")
            elif code == "FLD":
                messages.append("FLD" + self._display())
            elif code == "IFA":
                messages.append("IFA" + self._ifa())
            elif code == "IFV":
                messages.append("IFV" + self._ifv())
            elif (value := self.values.get(code, only.get(code))) is not None:
                messages.append(code + value)
        return messages

    def _lmd(self, param: str) -> Result:
        spec = self.fixture.behavior["signals"][self.signal]
        modes: list[str] = spec["modes"]
        current = self.values["LMD"]
        lock = float(self.fixture.profile["mode_lock_seconds"])
        if self.last_mode_change is not None and self.clock() - self.last_mode_change < lock:
            return silent()  # a mode set right after a mode change is ignored, no reply
        if param in {"UP", "DOWN"}:
            step = 1 if param == "UP" else -1
            index = modes.index(current) if current in modes else -step
            target = modes[(index + step) % len(modes)]
        elif param == "MUSIC":
            target = "0C"
        else:
            target = param.upper()
        if target not in modes:
            return refuse("LMD")
        if target == current:
            return Result(broadcast=["LMD" + target])
        self._mark_mode(target)
        names = self.fixture.behavior["mode_names"]
        name = spec["names"].get(target) or names.get(target, target)
        shown = name.center(DIMENSION)[:DIMENSION].encode("latin-1").hex().upper()
        record = self._pick("LMD", target)
        extra = [p for p in record.pushes if not p.startswith("FLD")] if record else []
        self._apply(extra)
        return Result(broadcast=["LMD" + target, *extra, "FLD" + shown])

    def _sli(self, param: str) -> Result:
        record = self._pick("SLI", param)
        if record is not None and record.kind == "refused":
            return refuse("SLI")
        sid = param.upper()
        if sid not in self.fixture.inputs:
            return refuse("SLI")
        if sid == self.values["SLI"]:
            return Result(broadcast=["SLI" + sid])
        behavior = self.fixture.behavior
        pushes = [p for p in (record.pushes if record else ()) if not p.startswith("FLD")]
        self.values["SLI"] = sid
        self._apply(pushes)
        self.values.update(behavior.get("input_effects", {}).get(sid, {}))
        old_signal = self.signal
        self.signal = behavior["input_signals"].get(sid, behavior["default_input_signal"])
        spec = behavior["signals"][self.signal]
        mode = self.input_modes.get(sid, spec["default_mode"])
        before = self.values["LMD"]
        self._mark_mode(mode)
        messages = ["SLI" + sid, "FLD" + self._display(), *pushes]
        if not any(m.startswith("LMD") for m in pushes) and mode != before:
            messages.append("LMD" + mode)
        if self.signal != old_signal:
            messages += ["IFA" + self._ifa(), "IFV" + self._ifv()]
        return Result(broadcast=messages)

    def _sleep(self, param: str) -> Result:
        rule = self.fixture.behavior["ranges"]["SLP"]
        cycle: list[str] = rule["cycle"]
        current = self.values["SLP"]
        if param in {"UP", "DOWN"}:
            index = cycle.index(current) if current in cycle else 0
            new = cycle[(index + (1 if param == "UP" else -1)) % len(cycle)]
        elif param == "OFF":
            new = "OFF"
        else:
            minutes = _hex(param)
            if minutes is None or not rule["min"] <= minutes <= rule["max"]:
                return refuse("SLP")
            new = f"{minutes:02X}"
        self.values["SLP"] = new
        return Result(broadcast=["SLP" + new])

    def _ranged(self, code: str, param: str) -> Result:
        rule = self.fixture.behavior["ranges"][code]
        step = int(rule.get("step", 1))
        current = self.values[code]
        if code == "TFR":
            return self._tone(param, rule)
        parse: Callable[[str], int | None] = _hex if code == "MVL" else _signed
        fmt: Callable[[int], str] = _fmt_hex if code == "MVL" else _fmt_signed(code)
        value = parse(current)
        if param in {"UP", "UP1"}:
            new = None if value is None else value + step
        elif param in {"DOWN", "DOWN1"}:
            new = None if value is None else value - step
        else:
            new = parse(param)
        if new is None or not rule["min"] <= new <= rule["max"]:
            return refuse(code)
        self.values[code] = fmt(new)
        messages = [code + self.values[code]]
        if code == "MVL":
            messages.append("FLD" + self._display())
        return Result(broadcast=messages)

    def _tone(self, param: str, rule: dict[str, int]) -> Result:
        current = self.values["TFR"]
        bass, treble = _tone(current)
        which, arg = param[:1], param[1:]
        if which not in {"B", "T"}:
            return refuse("TFR")
        old = bass if which == "B" else treble
        if arg == "UP":
            new: int | None = old + 1
        elif arg == "DOWN":
            new = old - 1
        else:
            new = _tone_value(arg)
        if new is None or not rule["min"] <= new <= rule["max"]:
            return refuse("TFR")
        bass, treble = (new, treble) if which == "B" else (bass, new)
        self.values["TFR"] = f"B{_fmt_tone(bass)}T{_fmt_tone(treble)}"
        return Result(broadcast=["TFR" + self.values["TFR"]])

    def _generic(self, code: str, param: str) -> Result:  # noqa: PLR0911
        behavior = self.fixture.behavior
        record = self._pick(code, param)
        mapping = behavior.get("set_maps", {}).get(code)
        if mapping is not None and param in mapping:
            new = mapping[param]
            if new == self.values.get(code):
                return Result(broadcast=[code + new])
            pushes = [p for p in (record.pushes if record else ()) if not p.startswith("FLD")]
            pushes = pushes or list(behavior.get("set_map_pushes", {}).get(code, []))
            self.values[code] = new
            self._apply(pushes)
            return Result(broadcast=[code + new, *pushes])
        if record is not None:
            return self._replay(record)
        if code not in self.fixture.on:
            return silent()
        if param in self.fixture.accepted_params(code) and self.fixture.on[code] != NA:
            self.values[code] = param
            if "same_silent" in self.fixture.kinds(code):
                return silent()
            return Result(broadcast=[code + param])
        return refuse(code)

    def _replay(self, record: Write) -> Result:
        code = record.code
        if record.kind == "refused":
            return refuse(code)
        if record.kind == "ignored":
            return Result(broadcast=[code + self.values.get(code, NA)])
        pushes = list(record.pushes)
        messages: list[str] = []
        if record.reply is not None and record.kind in {"changed", "same", "refused_push"}:
            messages.append(code + record.reply)
        if record.kind == "changed":
            self.values[code] = record.readback or record.reply or self.values.get(code, NA)
        self._apply(pushes)
        return Result(broadcast=[*messages, *pushes])

    # ----- helpers --------------------------------------------------------------------------

    def _pick(self, code: str, param: str) -> Write | None:
        """The recorded write that says what this set does in the current state."""
        records = self.fixture.writes.get((code, param), [])
        current = self.values.get(code)
        for record in records:
            if record.before == current:
                return record
        if param in RELATIVE_PARAMS:
            return None
        return next((r for r in records if r.kind in STATE_FREE_KINDS), None)

    def _apply(self, messages: list[str]) -> None:
        """Store what pushed messages say (a push is a state change)."""
        for message in messages:
            code, param = message[:3], message[3:]
            if code in NO_STATE or param == NA:
                continue
            if code == "LMD":
                self._mark_mode(param)
            else:
                self.values[code] = param

    def _mark_mode(self, mode: str) -> None:
        self.values["LMD"] = mode
        self.input_modes[self.values["SLI"]] = mode
        self.last_mode_change = self.clock()


def _hex(text: str) -> int | None:
    try:
        return int(text, 16) if len(text) == 2 else None  # noqa: PLR2004
    except ValueError:
        return None


def _fmt_hex(value: int) -> str:
    return f"{value:02X}"


def _signed(text: str) -> int | None:
    """Parse ``000``, ``0000``, ``+005``, ``-0A``: a sign and digits, hex for SWL and CTL."""
    if text.strip("0") == "":
        return 0
    if text[:1] not in {"+", "-"}:
        return None
    try:
        value = int(text[1:], 16 if len(text) == 3 else 10)  # noqa: PLR2004
    except ValueError:
        return None
    return value if text[0] == "+" else -value


def _fmt_signed(code: str) -> Callable[[int], str]:
    def fmt(value: int) -> str:
        sign = "+" if value > 0 else "-"
        if code == "AVS":
            return "0000" if value == 0 else f"{sign}{abs(value):03d}"
        return "000" if value == 0 else f"{sign}{abs(value):02X}"

    return fmt


def _tone(text: str) -> tuple[int, int]:
    bass_text, treble_text = text[1:].split("T")
    return _tone_value(bass_text) or 0, _tone_value(treble_text) or 0


def _tone_value(text: str) -> int | None:
    if text == "00":
        return 0
    if len(text) != 2 or text[0] not in {"+", "-"}:  # noqa: PLR2004
        return None
    try:
        value = int(text[1], 16)
    except ValueError:
        return None
    return value if text[0] == "+" else -value


def _fmt_tone(value: int) -> str:
    return "00" if value == 0 else f"{'+' if value > 0 else '-'}{abs(value):X}"
