"""The simulator's CI (config) records: answer ``s<CODE>QSTN<key>`` reads, apply partial sets.

Behaviour of the TX-RZ50 (specs/web-setup-backup.md): a read needs its key fields right after
``QSTN`` and is silent without or with an unknown key; a set carries the key fields and only the
changed fields, gets no reply, and is ignored (record unchanged) when the value is not valid for
the field, when the field is not settable, or for a family the receiver ignores (``CFC``).
A global field is shared by every record of its family.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from custom_components.onkyo_eiscp.lib import ci
from custom_components.onkyo_eiscp.lib.exceptions import CodecError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

QUERY = "QSTN"


class CiStore:
    """Every CI record of one simulated receiver, as ``(family, items)`` pairs."""

    def __init__(self, records: Iterable[str], ignored: Iterable[str] = ()) -> None:
        """Decode the raw records (``sLCC...``) and remember the families that ignore sets."""
        self.ignored = frozenset(ignored)
        self.records: list[list[tuple[str, str]]] = []
        self.codes: list[str] = []
        for raw in records:
            record = ci.decode(raw)
            self.codes.append(record.code)
            self.records.append(list(record.items))

    def handle(self, code: str, param: str) -> list[str]:
        """Answer one message whose code is ``sXXX`` (the ``s`` included); return the replies."""
        family = code[1:]
        if param.startswith(QUERY):
            return self._read(family, param[len(QUERY) :])
        self._write(family, param)
        return []

    # ----- reads ----------------------------------------------------------------------------

    def _read(self, asked: str, key_text: str) -> list[str]:
        family = self._family(asked)
        spec = ci.FAMILIES.get(family)
        names = spec.key_names if spec is not None else ()
        try:
            key = {name: value.strip() for name, value in ci.tokens(family, key_text)}
        except CodecError:
            return []
        if set(key) != set(names):
            return []  # without its key (or with a wrong one) the receiver stays silent
        found = self._find(family, key)
        if found is None:
            return []
        return [ci.PREFIX + family + "".join(name + value for name, value in found)]

    @staticmethod
    def _family(asked: str) -> str:
        spec = next((s for s in ci.FAMILIES.values() if s.query == asked), None)
        return spec.code if spec is not None else asked

    def _find(self, family: str, key: Mapping[str, str]) -> list[tuple[str, str]] | None:
        for code, items in zip(self.codes, self.records, strict=True):
            if code == family and all(
                _get(items, name, strip=True) == value for name, value in key.items()
            ):
                return items
        return None

    # ----- sets -----------------------------------------------------------------------------

    def _write(self, family: str, text: str) -> None:
        spec = ci.FAMILIES.get(family)
        if spec is None or family in self.ignored:
            return
        try:
            parsed = ci.tokens(family, text)
        except CodecError:
            return
        names = spec.key_names
        key = {name: value.strip() for name, value in parsed if name in names}
        if set(key) != set(names):
            return
        target = self._find(family, key)
        if target is None:
            return
        for name, value in parsed:
            if name in names:
                continue
            field = spec.fields.get(name)
            if field is None or not field.writable or _get(target, name) is None:
                continue
            if field.pattern is not None and re.fullmatch(field.pattern, value) is None:
                continue
            if len(value) != field.width:
                continue
            self._apply(family, name, value, target, shared=name in spec.shared)

    def _apply(
        self,
        family: str,
        name: str,
        value: str,
        target: list[tuple[str, str]],
        *,
        shared: bool,
    ) -> None:
        for code, items in zip(self.codes, self.records, strict=True):
            if code == family and (shared or items is target):
                for index, (item, _old) in enumerate(items):
                    if item == name:
                        items[index] = (name, value)


def _get(items: list[tuple[str, str]], name: str, *, strip: bool = False) -> str | None:
    for item, value in items:
        if item == name:
            return value.strip() if strip else value
    return None
