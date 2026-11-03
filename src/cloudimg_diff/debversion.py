"""Debian package version parsing and comparison.

This is a pure-Python port of the algorithm dpkg uses (``lib/dpkg/version.c``),
as specified in Debian Policy section 5.6.12. A version string has the form::

    [epoch:]upstream_version[-debian_revision]

Comparison is done field by field: the epoch numerically, then the upstream
version and the revision with ``verrevcmp``, which alternates between
non-digit runs (compared character by character with a custom ordering where
``~`` sorts before everything, even the end of the string) and digit runs
(compared numerically).
"""

from __future__ import annotations

import functools
import operator
import re
from dataclasses import dataclass

__all__ = ["DebVersion", "compare", "compare_op"]


def _isdigit(char: str) -> bool:
    # dpkg uses the C locale: only ASCII digits count.
    return "0" <= char <= "9"


def _order(char: str) -> int:
    """Sort weight of a single character inside a non-digit run."""
    if char == "" or _isdigit(char):
        return 0
    if "a" <= char <= "z" or "A" <= char <= "Z":
        return ord(char)
    if char == "~":
        return -1
    return ord(char) + 256


def _verrevcmp(a: str, b: str) -> int:
    i = j = 0
    len_a, len_b = len(a), len(b)

    def at(s: str, idx: int, n: int) -> str:
        return s[idx] if idx < n else ""

    while i < len_a or j < len_b:
        first_diff = 0
        # Non-digit prefix.
        while (i < len_a and not _isdigit(a[i])) or (j < len_b and not _isdigit(b[j])):
            ac = _order(at(a, i, len_a))
            bc = _order(at(b, j, len_b))
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        # Skip leading zeros of the digit run.
        while i < len_a and a[i] == "0":
            i += 1
        while j < len_b and b[j] == "0":
            j += 1
        # Digit run: the longer number wins, otherwise the first differing digit.
        while i < len_a and j < len_b and _isdigit(a[i]) and _isdigit(b[j]):
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len_a and _isdigit(a[i]):
            return 1
        if j < len_b and _isdigit(b[j]):
            return -1
        if first_diff:
            return first_diff
    return 0


@functools.total_ordering
@dataclass(frozen=True)
class DebVersion:
    """A parsed Debian version. Instances compare like ``dpkg --compare-versions``."""

    epoch: int
    upstream: str
    revision: str

    @classmethod
    def parse(cls, text: str) -> DebVersion:
        raw = text.strip()
        if not raw:
            raise ValueError("version string is empty")
        if any(c.isspace() for c in raw):
            raise ValueError(f"version {text!r} contains whitespace")

        epoch = 0
        rest = raw
        if ":" in raw:
            epoch_str, rest = raw.split(":", 1)
            if not epoch_str.isdigit():
                raise ValueError(f"epoch in {text!r} is not a number")
            epoch = int(epoch_str)

        upstream, sep, revision = rest.rpartition("-")
        if not sep:
            upstream, revision = rest, ""
        if not upstream:
            raise ValueError(f"version {text!r} has an empty upstream part")
        if sep and not revision:
            raise ValueError(f"version {text!r} has an empty revision")
        return cls(epoch=epoch, upstream=upstream, revision=revision)

    def __str__(self) -> str:
        out = f"{self.epoch}:" if self.epoch else ""
        out += self.upstream
        if self.revision:
            out += f"-{self.revision}"
        return out

    def _cmp(self, other: DebVersion) -> int:
        if self.epoch != other.epoch:
            return 1 if self.epoch > other.epoch else -1
        result = _verrevcmp(self.upstream, other.upstream)
        if result:
            return result
        return _verrevcmp(self.revision, other.revision)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DebVersion):
            return NotImplemented
        return self._cmp(other) == 0

    def __lt__(self, other: DebVersion) -> bool:
        return self._cmp(other) < 0

    def __hash__(self) -> int:
        # Versions that compare equal ("1.0", "1.00" and "1.0-0"; "0:1.0" and "1.0") must
        # hash equal, so hash a normalised form instead of the raw fields.
        return hash((self.epoch, _normalise(self.upstream), _normalise(self.revision)))


def _normalise(part: str) -> str:
    """Drop leading zeros from every digit run so that equal versions hash alike.

    verrevcmp skips leading zeros, so a run of zeros compares like no digits at all
    ("1.0" == "1."), which is why an all-zero run normalises to the empty string.
    """
    return re.sub(r"[0-9]+", lambda m: m.group().lstrip("0"), part)


def compare(a: str | DebVersion, b: str | DebVersion) -> int:
    """Return a negative number, zero or a positive number, like ``strcmp``."""
    va = a if isinstance(a, DebVersion) else DebVersion.parse(a)
    vb = b if isinstance(b, DebVersion) else DebVersion.parse(b)
    result = va._cmp(vb)
    return (result > 0) - (result < 0)


_OPERATORS = {
    "lt": operator.lt,
    "le": operator.le,
    "eq": operator.eq,
    "ne": operator.ne,
    "ge": operator.ge,
    "gt": operator.gt,
    "<<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
    ">=": operator.ge,
    ">>": operator.gt,
}


def compare_op(a: str, op: str, b: str) -> bool:
    """Evaluate ``a op b`` with the same operator names as ``dpkg --compare-versions``."""
    try:
        func = _OPERATORS[op]
    except KeyError:
        valid = ", ".join(_OPERATORS)
        raise ValueError(f"unknown operator {op!r} (expected one of: {valid})") from None
    return func(compare(a, b), 0)
