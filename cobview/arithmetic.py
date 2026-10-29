"""COBOL rules for storing a number into a field.

A view has one of two policies, chosen with ``arithmetic=``:

``"strict"`` (default)
    Nothing is lost silently.  Extra decimal places, values too large for
    the PIC, and negatives in unsigned fields all raise.

``"cobol"``
    Assignment behaves like COBOL's ``COMPUTE target = value`` as compiled
    by GnuCOBOL, byte for byte:

    * extra decimal places are truncated (or rounded inside :func:`rounded`);
    * a negative value stored in an unsigned field keeps its absolute value;
    * a value too large raises :class:`SizeError` and leaves the field
      unchanged (``ON SIZE ERROR``), or inside ``on_size_error("truncate")``
      loses its high-order digits like ``COMPUTE`` without that phrase;
    * ``COMP`` / ``BINARY`` items are limited by their PIC digits, while
      ``COMP-5`` and ``BINARY-LONG``-style items are limited by the size of
      the binary and wrap around when truncated.

Both policies honour :func:`rounded`, which takes the eight ``ROUNDED MODE``
names of COBOL 2014.  These rules were derived from, and are tested
against, GnuCOBOL itself (see ``cobol/ARITH.cbl``).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
)

from .copybook import Field
from .errors import CobolDataError, SizeError

__all__ = ["ARITHMETIC", "ROUNDING_MODES", "SizeError", "on_size_error", "rounded"]

ARITHMETIC = ("strict", "cobol")

ROUNDING_MODES = {
    "AWAY-FROM-ZERO": ROUND_UP,
    "NEAREST-AWAY-FROM-ZERO": ROUND_HALF_UP,  # what plain ROUNDED means
    "NEAREST-EVEN": ROUND_HALF_EVEN,
    "NEAREST-TOWARD-ZERO": ROUND_HALF_DOWN,
    "TOWARD-GREATER": ROUND_CEILING,
    "TOWARD-LESSER": ROUND_FLOOR,
    "TRUNCATION": ROUND_DOWN,
    "PROHIBITED": "PROHIBITED",
}

_rounding: ContextVar[str | None] = ContextVar("cobview_rounding", default=None)
_size_error: ContextVar[str] = ContextVar("cobview_size_error", default="raise")

# usages limited by the size of the binary rather than by PIC digits
_CAPACITY_USAGES = {"COMP-5", "COMP-X", "BINARY-CHAR", "BINARY-SHORT", "BINARY-LONG",
                    "BINARY-DOUBLE", "POINTER", "INDEX"}


@contextmanager
def rounded(mode: str = "NEAREST-AWAY-FROM-ZERO"):
    """Store with COBOL's ``ROUNDED MODE IS mode`` inside this block.

    ``with cobview.rounded(): rec.AMOUNT = Decimal("1.235")`` stores 1.24.
    """
    key = mode.upper().replace("_", "-").replace(" ", "-")
    if key not in ROUNDING_MODES:
        raise ValueError(f"unknown ROUNDED MODE {mode!r}; use one of {sorted(ROUNDING_MODES)}")
    token = _rounding.set(key)
    try:
        yield
    finally:
        _rounding.reset(token)


@contextmanager
def on_size_error(action: str):
    """``"raise"`` (default) or ``"truncate"`` for values that do not fit.

    Only views with ``arithmetic="cobol"`` truncate; strict views always raise.
    """
    if action not in ("raise", "truncate"):
        raise ValueError("action must be 'raise' or 'truncate'")
    token = _size_error.set(action)
    try:
        yield
    finally:
        _size_error.reset(token)


def to_decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise CobolDataError("booleans are not numbers here")
    if isinstance(value, float):
        value = Decimal(repr(value))
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise CobolDataError(f"{value!r} is not a number") from None
    if not d.is_finite():
        raise CobolDataError(f"{value!r} is not a finite number")
    return d


def capacity_limited(field: Field) -> bool:
    return field.kind == "binary" and field.usage in _CAPACITY_USAGES


def prepare(field: Field, value, arithmetic: str = "strict") -> tuple[int, bool]:
    """Apply the store rules; return ``(magnitude, negative)`` of the stored integer.

    The integer is the value times ``10 ** field.scale``.  ``negative`` can
    be true with a zero magnitude: COBOL keeps the sign when high-order
    truncation leaves only zeros.
    """
    if arithmetic not in ARITHMETIC:
        raise ValueError(f"arithmetic must be one of {ARITHMETIC}")
    strict = arithmetic == "strict"
    d = to_decimal(value)
    mode = _rounding.get()
    q = d.scaleb(field.scale)

    if mode == "PROHIBITED":
        # GnuCOBOL judges by the decimal places the source carries, not by
        # whether they happen to be zero: 1.200000 into V99 is a size error.
        # Zero itself never is (libcob numeric.c, cob_decimal_do_round).
        if d != 0 and d.as_tuple().exponent < -field.scale:
            raise SizeError(
                f"{d} has more than {field.scale} decimal places and "
                f"ROUNDED MODE IS PROHIBITED ({field.name})"
            )
    elif q != q.to_integral_value():
        if mode is None:
            if strict:
                raise CobolDataError(
                    f"{d} has more than {field.scale} decimal places for {field.name}; "
                    "use cobview.rounded() or arithmetic='cobol'"
                )
            q = q.to_integral_value(rounding=ROUND_DOWN)
        else:
            q = q.to_integral_value(rounding=ROUNDING_MODES[mode])
    n = int(q)
    negative = n < 0
    magnitude = -n if negative else n

    if negative and not field.signed:
        if strict:
            raise CobolDataError(f"{field.name} is unsigned; cannot store {d}")
        negative = False  # COBOL stores the absolute value

    if field.kind == "binary" and (capacity_limited(field) and not strict or not field.digits):
        bits = field.size * 8
        signed_value = -magnitude if negative else magnitude
        if field.signed:
            # symmetric: GnuCOBOL raises SIZE ERROR for -32768 in a 2-byte item
            fits = magnitude < (1 << (bits - 1))
        else:
            fits = magnitude < (1 << bits)
        if fits:
            return magnitude, negative
        if strict or _size_error.get() == "raise":
            raise _size(field, d)
        wrapped = signed_value & ((1 << bits) - 1)
        if field.signed and wrapped >= 1 << (bits - 1):
            wrapped -= 1 << bits
        return abs(wrapped), wrapped < 0

    limit = 10**field.digits
    if magnitude < limit:
        return magnitude, negative
    if strict or _size_error.get() == "raise":
        raise _size(field, d)
    return magnitude % limit, negative


def _size(field: Field, d: Decimal) -> SizeError:
    pic = f" PIC {field.pic}" if field.pic else f" {field.usage}"
    return SizeError(f"{d} does not fit {field.name}{pic} (ON SIZE ERROR)")


def prepare_text(field: Field, raw: bytes, arithmetic: str) -> bytes:
    """Alphanumeric MOVE: pad on the right; too long raises or truncates."""
    if len(raw) <= field.size:
        return raw
    if arithmetic == "strict" or _size_error.get() == "raise":
        raise SizeError(
            f"{len(raw)} bytes do not fit {field.name} PIC {field.pic} ({field.size} bytes)"
        )
    return raw[: field.size]
