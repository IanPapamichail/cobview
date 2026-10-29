import random
from decimal import Decimal

import pytest

from cobview import CobolDataError
from cobview.codecs import decode_packed, decode_zoned, encode_packed, encode_zoned


@pytest.mark.parametrize(
    "raw, scale, expected",
    [
        (b"\x12\x34\x5c", 0, 12345),
        (b"\x12\x34\x5d", 0, -12345),
        (b"\x12\x34\x5f", 0, 12345),  # unsigned
        (b"\x00\x12\x34\x56\x7c", 2, Decimal("12345.67")),
        (b"\x99\x99\x99\x99\x9d", 2, Decimal("-9999999.99")),
        (b"\x0c", 0, 0),
        (b"\x00\x00\x0c", 2, Decimal("0.00")),
    ],
)
def test_packed_known_vectors(raw, scale, expected):
    value = decode_packed(raw, scale)
    assert value == expected and type(value) is type(expected)
    assert encode_packed(expected, len(raw), scale, signed=raw[-1] & 0xF != 0xF) == raw


@pytest.mark.parametrize("raw", [b"\x1a\x2c", b"\x12\x34", b"\x12\x39", b""])
def test_packed_rejects_garbage(raw):
    with pytest.raises(CobolDataError):
        decode_packed(raw)


@pytest.mark.parametrize(
    "raw, kwargs, expected",
    [
        (b"0000777", dict(scale=2, signed=True), Decimal("7.77")),
        (b"000777p", dict(scale=2, signed=True), Decimal("-77.70")),  # GnuCOBOL
        (b"00077}", dict(signed=True), -770),  # IBM-style overpunch in ASCII
        (b"00077J", dict(signed=True), -771),
        (b"00077A", dict(signed=True), 771),
        (b"-0042", dict(signed=True, sign_leading=True, sign_separate=True), -42),
        (b"0042+", dict(signed=True, sign_separate=True), 42),
        (b"p042", dict(signed=True, sign_leading=True), -42),
        (b"\xf0\xf1\xf2\xd3", dict(signed=True, ebcdic=True), -123),
        (b"\xf0\xf1\xf2\xc3", dict(signed=True, ebcdic=True), 123),
        (b"\xf0\xf1\xf2\xf3", dict(ebcdic=True), 123),
    ],
)
def test_zoned_known_vectors(raw, kwargs, expected):
    assert decode_zoned(raw, **kwargs) == expected


@pytest.mark.parametrize("raw", [b"00 7", b"+007", b"0x07", b""])
def test_zoned_rejects_garbage(raw):
    with pytest.raises(CobolDataError):
        decode_zoned(raw, signed=False)


def test_packed_round_trip_random():
    rng = random.Random(1)
    for _ in range(2000):
        digits = rng.randint(1, 18)
        scale = rng.randint(0, digits)
        size = digits // 2 + 1
        n = rng.randint(-(10**digits) + 1, 10**digits - 1)
        value = Decimal(n).scaleb(-scale) if scale else n
        raw = encode_packed(value, size, scale)
        assert len(raw) == size
        assert decode_packed(raw, scale) == value


@pytest.mark.parametrize("ebcdic", [False, True])
@pytest.mark.parametrize("leading", [False, True])
@pytest.mark.parametrize("separate", [False, True])
def test_zoned_round_trip_random(ebcdic, leading, separate):
    rng = random.Random(2)
    for _ in range(500):
        digits = rng.randint(1, 18)
        scale = rng.randint(0, digits)
        n = rng.randint(-(10**digits) + 1, 10**digits - 1)
        value = Decimal(n).scaleb(-scale) if scale else n
        kw = dict(sign_leading=leading, sign_separate=separate, ebcdic=ebcdic)
        raw = encode_zoned(value, digits, scale, True, **kw)
        assert len(raw) == digits + (1 if separate else 0)
        assert decode_zoned(raw, scale, True, **kw) == value


def test_overflow_and_precision_are_errors_not_silent_truncation():
    with pytest.raises(CobolDataError, match="does not fit"):
        encode_packed(100000, 3)
    with pytest.raises(CobolDataError, match="decimal places"):
        encode_packed(Decimal("1.234"), 3, scale=2)
    with pytest.raises(CobolDataError, match="unsigned"):
        encode_zoned(-1, 3, signed=False)
