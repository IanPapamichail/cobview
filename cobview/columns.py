"""Whole-column access with NumPy.

Fixed-length records are a strided array in disguise: field ``F`` of record
``i`` starts at ``i * record_size + F.offset``.  NumPy can describe that
with ``strides`` and point straight at the original buffer, so binary
columns cost nothing to "load".  Packed and zoned decimals have no NumPy
dtype, so they are decoded here with vectorized nibble arithmetic.
"""

from __future__ import annotations

import numpy as np

from .codecs import _ASCII_SIGN, _EBCDIC_SIGN, CobolDataError
from .copybook import Field

__all__ = ["column", "bytes_column", "columns"]

_INVALID = 255


def _shape_strides(records, f: Field):
    n = len(records)
    shape = (n,) + tuple(count for count, _ in f.dims)
    strides = (records.layout.size,) + tuple(stride for _, stride in f.dims)
    return shape, strides


def _strided(records, f: Field, dtype, extra_shape=(), extra_strides=()):
    """A zero-copy ndarray over ``f`` in every record (and every occurrence)."""
    shape, strides = _shape_strides(records, f)
    shape += tuple(extra_shape)
    strides += tuple(extra_strides)
    if shape[0] == 0:
        return np.empty(shape, dtype=dtype)
    return np.ndarray(
        shape, dtype=dtype, buffer=records.buffer, offset=f.offset, strides=strides
    )


def _byte_block(records, f: Field) -> np.ndarray:
    """uint8 array of shape (n, *occurs, f.size); zero-copy."""
    return _strided(records, f, np.uint8, (f.size,), (1,))


def _fail(records, f: Field, bad: np.ndarray, what: str):
    where = np.argwhere(bad)[0]
    rec = int(where[0])
    occ = "".join(f"[{int(k)}]" for k in where[1:])
    raw = bytes(_byte_block(records, f)[tuple(where)])
    raise CobolDataError(f"{f.path}{occ}: invalid {what} in record {rec}: {raw!r}")


def _check_digits(f: Field, n: int) -> None:
    if n > 18:
        raise CobolDataError(
            f"{f.path}: {n}-digit numbers do not fit int64; read them per record instead"
        )


def _accumulate(columns: np.ndarray, base: int) -> np.ndarray:
    """Horner's rule along the last axis: ((c0*base + c1)*base + c2)..."""
    values = np.zeros(columns.shape[:-1], dtype=np.int64)
    for k in range(columns.shape[-1]):
        values *= base
        values += columns[..., k]
    return values


# byte -> two decimal digits (0..99) for every byte but the last
_PACKED_PAIR = np.full(256, _INVALID, dtype=np.uint8)
# last byte -> its single digit; its low nibble is the sign
_PACKED_LAST = np.full(256, _INVALID, dtype=np.uint8)
_PACKED_NEG = np.zeros(256, dtype=bool)
for _hi in range(10):
    for _lo in range(10):
        _PACKED_PAIR[_hi * 16 + _lo] = _hi * 10 + _lo
    for _sign in range(0x0A, 0x10):
        _PACKED_LAST[_hi * 16 + _sign] = _hi
        _PACKED_NEG[_hi * 16 + _sign] = _sign in (0x0B, 0x0D)


def _packed(records, f: Field) -> np.ndarray:
    _check_digits(f, 2 * f.size - 1)
    blk = _byte_block(records, f)
    pairs = _PACKED_PAIR[blk[..., :-1]]
    last = blk[..., -1]
    last_digit = _PACKED_LAST[last]
    bad = (pairs == _INVALID).any(axis=-1) | (last_digit == _INVALID)
    if bad.any():
        _fail(records, f, bad, "packed decimal")
    values = _accumulate(pairs, 100) * 10 + last_digit
    return np.where(_PACKED_NEG[last], -values, values)


def _tables(ebcdic: bool):
    plain = np.full(256, _INVALID, dtype=np.uint8)
    zero = 0xF0 if ebcdic else 0x30
    plain[zero : zero + 10] = np.arange(10, dtype=np.uint8)
    sign_digit = np.full(256, _INVALID, dtype=np.uint8)
    sign_neg = np.zeros(256, dtype=bool)
    for byte, (digit, neg) in (_EBCDIC_SIGN if ebcdic else _ASCII_SIGN).items():
        sign_digit[byte] = digit
        sign_neg[byte] = neg
    return plain, sign_digit, sign_neg


def _zoned(records, f: Field) -> np.ndarray:
    _check_digits(f, f.digits)
    ebcdic = records.layout.options.ebcdic
    blk = _byte_block(records, f)
    plain, sign_digit, sign_neg = _tables(ebcdic)
    negative = np.zeros(blk.shape[:-1], dtype=bool)
    if f.signed and f.sign_separate:
        pos = 0 if f.sign_leading else f.size - 1
        sign_bytes = blk[..., pos]
        minus, plus = (0x60, 0x4E) if ebcdic else (ord("-"), ord("+"))
        space = 0x40 if ebcdic else 0x20
        bad_sign = (sign_bytes != minus) & (sign_bytes != plus) & (sign_bytes != space)
        negative = sign_bytes == minus
        body = blk[..., 1:] if f.sign_leading else blk[..., :-1]
        digits = plain[body]
    elif f.signed:
        pos = 0 if f.sign_leading else f.size - 1
        digits = plain[blk]
        digits[..., pos] = sign_digit[blk[..., pos]]
        negative = sign_neg[blk[..., pos]]
        bad_sign = np.zeros_like(negative)
    else:
        digits = plain[blk]
        bad_sign = np.zeros(blk.shape[:-1], dtype=bool)
    bad = (digits == _INVALID).any(axis=-1) | bad_sign
    if bad.any():
        _fail(records, f, bad, "zoned decimal")
    values = _accumulate(digits, 10)
    return np.where(negative, -values, values)


def _binary_dtype(f: Field) -> np.dtype:
    order = "<" if f.byteorder == "little" else ">"
    code = ("i" if f.signed else "u") if f.kind == "binary" else "f"
    return np.dtype(f"{order}{code}{f.size}")


def _scale(values: np.ndarray, f: Field, exact: bool) -> np.ndarray:
    if f.scale == 0 or exact:
        return values
    return values / (10.0**f.scale)


def _field(records, name) -> Field:
    return name if isinstance(name, Field) else records.layout.find(name)


def column(records, name, *, exact: bool = False) -> np.ndarray:
    f = _field(records, name)
    if f.is_group:
        raise TypeError(f"{f.name} is a group; use bytes_column() for its raw bytes")
    if f.kind in ("binary", "float"):
        values = _strided(records, f, _binary_dtype(f))
        return values if f.kind == "float" else _scale(values, f, exact)
    if f.kind == "packed":
        return _scale(_packed(records, f), f, exact)
    if f.kind == "zoned":
        return _scale(_zoned(records, f), f, exact)
    raw = bytes_column(records, f)
    text = np.char.decode(raw, records.layout.options.encoding, errors="replace")
    return np.char.rstrip(text, " ") if f.kind == "alnum" else np.char.strip(text)


def bytes_column(records, name) -> np.ndarray:
    f = _field(records, name)
    return _strided(records, f, np.dtype(f"S{f.size}"))


def columns(records, names=None, *, exact: bool = False) -> dict:
    """Decode many columns at once; OCCURS items expand to ``NAME[i]`` keys."""
    if names is None:
        fields = [
            f
            for f in records.layout.elementary()
            if not _under_redefines(f)
        ]
    else:
        fields = [records.layout.find(n) for n in names]
    out = {}
    for f in fields:
        values = column(records, f, exact=exact)
        if values.ndim == 1:
            out[f.name] = values
            continue
        for idx in np.ndindex(values.shape[1:]):
            key = f.name + "".join(f"[{k}]" for k in idx)
            out[key] = values[(slice(None),) + idx]
    return out


def _under_redefines(f: Field) -> bool:
    node = f
    while node is not None:
        if node.redefines:
            return True
        node = node.parent
    return False
