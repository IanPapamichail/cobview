"""Encode and decode single COBOL values.

Numbers come back as ``int`` when the PIC has no decimal places and as
``decimal.Decimal`` otherwise, so money never passes through a float.
"""

from __future__ import annotations

import struct
from decimal import Decimal

from .arithmetic import prepare, prepare_text, to_decimal
from .copybook import Field, Options
from .errors import CobolDataError, SizeError

__all__ = [
    "CobolDataError",
    "SizeError",
    "decode",
    "encode",
    "decode_packed",
    "encode_packed",
    "decode_zoned",
    "encode_zoned",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scaled(n: int, scale: int):
    return Decimal(n).scaleb(-scale) if scale else n


def _unscaled(value, scale: int) -> int:
    """Turn a Python number into the integer COBOL stores (value * 10**scale)."""
    q = to_decimal(value).scaleb(scale)
    if q != q.to_integral_value():
        raise CobolDataError(f"{value} has more than {scale} decimal places")
    return int(q)


# ---------------------------------------------------------------------------
# packed decimal (COMP-3)
# ---------------------------------------------------------------------------

_PACKED_POSITIVE = set("acef")
_PACKED_NEGATIVE = set("bd")


def decode_packed(data, scale: int = 0):
    """``b'\\x12\\x34\\x5c'`` -> ``12345`` (or ``Decimal('123.45')`` with scale 2)."""
    h = bytes(data).hex()
    if not h:
        raise CobolDataError("empty packed decimal")
    sign = h[-1]
    digits = h[:-1]
    if not digits.isdigit():
        raise CobolDataError(f"invalid packed decimal digits: {h}")
    if sign in _PACKED_NEGATIVE:
        n = -int(digits)
    elif sign in _PACKED_POSITIVE:
        n = int(digits)
    else:
        raise CobolDataError(f"invalid packed decimal sign nibble: {h}")
    return _scaled(n, scale)


def encode_packed(value, size: int, scale: int = 0, signed: bool = True) -> bytes:
    n = _unscaled(value, scale)
    if abs(n) >= 10 ** (size * 2 - 1):
        raise SizeError(f"{value} does not fit in {size} packed bytes")
    if n < 0 and not signed:
        raise CobolDataError("negative value for an unsigned packed field")
    return _pack(abs(n), n < 0, size, signed)


def _pack(magnitude: int, negative: bool, size: int, signed: bool) -> bytes:
    sign = "d" if negative else ("c" if signed else "f")
    return bytes.fromhex(f"{magnitude:0{size * 2 - 1}d}{sign}")


# ---------------------------------------------------------------------------
# zoned decimal (USAGE DISPLAY numerics)
# ---------------------------------------------------------------------------

# byte -> (digit, negative) for the byte that carries an overpunched sign
_ASCII_SIGN = {0x30 + d: (d, False) for d in range(10)}
_ASCII_SIGN.update({0x70 + d: (d, True) for d in range(10)})  # GnuCOBOL / MF
_ASCII_SIGN[ord("{")] = (0, False)  # IBM-style overpunch in ASCII
_ASCII_SIGN.update({ord("A") + d - 1: (d, False) for d in range(1, 10)})
_ASCII_SIGN[ord("}")] = (0, True)
_ASCII_SIGN.update({ord("J") + d - 1: (d, True) for d in range(1, 10)})

_EBCDIC_SIGN = {}
for _zone, _neg in ((0xF0, False), (0xC0, False), (0xA0, False), (0xE0, False),
                    (0xD0, True), (0xB0, True)):
    _EBCDIC_SIGN.update({_zone + d: (d, _neg) for d in range(10)})

_EBCDIC_DIGITS = bytes.maketrans(bytes(range(0xF0, 0xFA)), b"0123456789")
_TO_EBCDIC_DIGITS = bytes.maketrans(b"0123456789", bytes(range(0xF0, 0xFA)))

_SEPARATE_SIGNS = {
    False: {ord("+"): False, ord("-"): True, ord(" "): False},
    True: {0x4E: False, 0x60: True, 0x40: False},
}


def decode_zoned(
    data,
    scale: int = 0,
    signed: bool = False,
    *,
    sign_leading: bool = False,
    sign_separate: bool = False,
    ebcdic: bool = False,
):
    """Decode a USAGE DISPLAY number such as ``b'0000777'`` or ``b'000777p'``."""
    b = bytes(data)
    if not b:
        raise CobolDataError("empty zoned decimal")
    negative = False
    if signed and sign_separate:
        sign_byte = b[0] if sign_leading else b[-1]
        body = b[1:] if sign_leading else b[:-1]
        try:
            negative = _SEPARATE_SIGNS[ebcdic][sign_byte]
        except KeyError:
            raise CobolDataError(f"invalid separate sign byte in {b!r}") from None
    elif signed:
        pos = 0 if sign_leading else len(b) - 1
        table = _EBCDIC_SIGN if ebcdic else _ASCII_SIGN
        try:
            digit, negative = table[b[pos]]
        except KeyError:
            raise CobolDataError(f"invalid zoned sign byte in {b!r}") from None
        body = bytearray(b)
        body[pos] = 0xF0 + digit if ebcdic else 0x30 + digit
        body = bytes(body)
    else:
        body = b
    if ebcdic:
        if any(c < 0xF0 or c > 0xF9 for c in body):
            raise CobolDataError(f"invalid zoned digits in {b!r}")
        body = body.translate(_EBCDIC_DIGITS)
    elif not body.isdigit():
        raise CobolDataError(f"invalid zoned digits in {b!r}")
    n = int(body)
    return _scaled(-n if negative else n, scale)


def encode_zoned(
    value,
    digits: int,
    scale: int = 0,
    signed: bool = False,
    *,
    sign_leading: bool = False,
    sign_separate: bool = False,
    ebcdic: bool = False,
) -> bytes:
    n = _unscaled(value, scale)
    if abs(n) >= 10**digits:
        raise SizeError(f"{value} does not fit in {digits} digits")
    if n < 0 and not signed:
        raise CobolDataError("negative value for an unsigned field")
    return _zone(abs(n), n < 0, digits, signed, sign_leading, sign_separate, ebcdic)


def _zone(magnitude: int, negative: bool, digits: int, signed: bool,
          sign_leading: bool, sign_separate: bool, ebcdic: bool) -> bytes:
    body = bytearray(f"{magnitude:0{digits}d}".encode("ascii"))
    if ebcdic:
        body = bytearray(bytes(body).translate(_TO_EBCDIC_DIGITS))
    if signed and sign_separate:
        if ebcdic:
            sign = b"\x60" if negative else b"\x4e"
        else:
            sign = b"-" if negative else b"+"
        return sign + bytes(body) if sign_leading else bytes(body) + sign
    if signed:
        pos = 0 if sign_leading else len(body) - 1
        d = body[pos] & 0x0F
        if ebcdic:
            body[pos] = (0xD0 if negative else 0xC0) + d
        elif negative:
            body[pos] = 0x70 + d  # GnuCOBOL / Micro Focus convention
    return bytes(body)


# ---------------------------------------------------------------------------
# field-level dispatch
# ---------------------------------------------------------------------------


def decode(field: Field, data, options: Options):
    """Decode the bytes of one occurrence of an elementary ``field``."""
    kind = field.kind
    if kind == "alnum" or kind == "edited":
        text = bytes(data).decode(options.encoding, errors="replace")
        return text.rstrip(" ") if kind == "alnum" else text.strip()
    if kind == "packed":
        return decode_packed(data, field.scale)
    if kind == "zoned":
        return decode_zoned(
            data,
            field.scale,
            field.signed,
            sign_leading=field.sign_leading,
            sign_separate=field.sign_separate,
            ebcdic=options.ebcdic,
        )
    if kind == "binary":
        n = int.from_bytes(data, field.byteorder, signed=field.signed)
        return _scaled(n, field.scale)
    if kind == "float":
        if options.ebcdic:
            raise CobolDataError("IBM hexadecimal floating point is not supported yet")
        fmt = ("<" if field.byteorder == "little" else ">") + ("f" if field.size == 4 else "d")
        return struct.unpack(fmt, data)[0]
    raise CobolDataError(f"cannot decode a {kind} item ({field.name})")


def encode(field: Field, value, options: Options, arithmetic: str = "strict") -> bytes:
    """Encode ``value`` into exactly ``field.size`` bytes under the given rules."""
    kind = field.kind
    if kind in ("alnum", "edited"):
        if isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
        else:
            raw = str(value).encode(options.encoding)
        raw = prepare_text(field, raw, arithmetic)
        return raw + " ".encode(options.encoding) * (field.size - len(raw))
    if kind == "float":
        if options.ebcdic:
            raise CobolDataError("IBM hexadecimal floating point is not supported yet")
        fmt = ("<" if field.byteorder == "little" else ">") + ("f" if field.size == 4 else "d")
        return struct.pack(fmt, float(to_decimal(value)))
    if kind not in ("packed", "zoned", "binary"):
        raise CobolDataError(f"cannot encode a {kind} item ({field.name})")
    magnitude, negative = prepare(field, value, arithmetic)
    if kind == "packed":
        return _pack(magnitude, negative, field.size, field.signed)
    if kind == "zoned":
        return _zone(magnitude, negative, field.digits, field.signed,
                     field.sign_leading, field.sign_separate, options.ebcdic)
    n = -magnitude if negative else magnitude
    return n.to_bytes(field.size, field.byteorder, signed=field.signed)
