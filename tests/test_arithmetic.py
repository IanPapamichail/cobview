"""COBOL arithmetic rules: unit tests, plus a differential test against GnuCOBOL.

The differential test calls cobol/ARITH.cbl in-process through
cobview.Program.  For thousands of random values and every statement form
(COMPUTE with and without ON SIZE ERROR, and all eight ROUNDED MODEs) it
compares, byte for byte, what GnuCOBOL stored in nine kinds of field with
what cobview stores under arithmetic="cobol".
"""

import random
import shutil
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path

import pytest

import cobview
from cobview import CobolDataError, Layout, SizeError

COBOL_DIR = Path(__file__).resolve().parents[1] / "cobol"

LAYOUT = Layout.from_copybook(
    """
       01 R.
          05 AMOUNT   PIC S9(5)V99 COMP-3.
          05 COUNT    PIC 9(4).
          05 HITS     PIC 9(4) COMP-5.
          05 TALLY    PIC S9(4) COMP.
          05 NAME     PIC X(5).
    """
)


def fresh(arithmetic):
    return cobview.view(bytearray(LAYOUT.size), LAYOUT, arithmetic=arithmetic)


# -- unit tests: the rules on their own ---------------------------------------


def test_strict_is_the_default_and_never_loses_data():
    rec = fresh("strict")
    with pytest.raises(CobolDataError, match="decimal places"):
        rec.AMOUNT = Decimal("1.239")
    with pytest.raises(SizeError):
        rec.COUNT = 10000
    with pytest.raises(CobolDataError, match="unsigned"):
        rec.COUNT = -1
    with pytest.raises(SizeError):
        rec.NAME = "TOO LONG"


def test_rounded_works_in_both_modes():
    for mode in ("strict", "cobol"):
        rec = fresh(mode)
        with cobview.rounded():
            rec.AMOUNT = Decimal("1.235")
        assert rec.AMOUNT == Decimal("1.24")
        with cobview.rounded("NEAREST-EVEN"):
            rec.AMOUNT = Decimal("1.245")
        assert rec.AMOUNT == Decimal("1.24")
        with cobview.rounded("nearest even"):  # spelling is forgiving
            rec.AMOUNT = Decimal("1.255")
        assert rec.AMOUNT == Decimal("1.26")


def test_cobol_mode_truncates_decimals_and_takes_absolute_values():
    rec = fresh("cobol")
    rec.AMOUNT = Decimal("1.239")
    assert rec.AMOUNT == Decimal("1.23")
    rec.AMOUNT = Decimal("-1.239")
    assert rec.AMOUNT == Decimal("-1.23")
    rec.COUNT = -42  # unsigned: COBOL keeps the absolute value
    assert rec.COUNT == 42
    rec.AMOUNT = 0.1  # floats go through their shortest repr, not binary noise
    assert rec.AMOUNT == Decimal("0.10")


def test_size_error_leaves_the_field_unchanged():
    rec = fresh("cobol")
    rec.COUNT = 1234
    before = bytes(rec.raw)
    with pytest.raises(SizeError, match="ON SIZE ERROR"):
        rec.COUNT = 12345
    assert bytes(rec.raw) == before
    with pytest.raises(SizeError):
        with cobview.rounded():
            rec.AMOUNT = Decimal("99999.995")  # rounding itself overflows


def test_truncate_on_size_error_matches_cobol_without_the_phrase():
    rec = fresh("cobol")
    with cobview.on_size_error("truncate"):
        rec.COUNT = 12345     # display: high-order digits dropped
        rec.TALLY = -12345    # COMP: PIC digits, sign kept
        rec.HITS = 70000      # COMP-5: wraps at 2**16
        rec.NAME = "TOO LONG"  # text: right-truncated like MOVE
    assert (rec.COUNT, rec.TALLY, rec.HITS, rec.NAME) == (2345, -2345, 4464, "TOO L")


def test_comp5_is_limited_by_its_binary_not_its_pic_in_cobol_mode():
    rec = fresh("cobol")
    rec.HITS = 65535  # PIC 9(4) COMP-5 still holds 65535
    assert rec.HITS == 65535
    with pytest.raises(SizeError):
        rec.HITS = 65536
    strict = fresh("strict")
    with pytest.raises(SizeError):
        strict.HITS = 10000  # strict keeps to the PIC


def test_prohibited_judges_the_digits_the_value_carries():
    rec = fresh("cobol")
    with cobview.rounded("PROHIBITED"):
        rec.AMOUNT = Decimal("1.25")
        with pytest.raises(SizeError, match="PROHIBITED"):
            rec.AMOUNT = Decimal("1.250")  # three places, even though zero


def test_negative_zero_survives_high_order_truncation():
    rec = fresh("cobol")
    with cobview.on_size_error("truncate"):
        rec.AMOUNT = Decimal("-100000.00")  # only zeros left, sign kept
    assert bytes(rec.raw[:4]) == bytes.fromhex("0000000d")


def test_contexts_nest_and_reset():
    rec = fresh("cobol")
    with cobview.rounded():
        with cobview.rounded("TOWARD-LESSER"):
            rec.AMOUNT = Decimal("1.239")
            assert rec.AMOUNT == Decimal("1.23")
        rec.AMOUNT = Decimal("1.239")
        assert rec.AMOUNT == Decimal("1.24")
    rec.AMOUNT = Decimal("1.239")
    assert rec.AMOUNT == Decimal("1.23")
    with pytest.raises(ValueError):
        with cobview.rounded("BANKERS"):
            pass


# -- differential test against GnuCOBOL ----------------------------------------

TARGETS = ["T-ZONED", "T-UZONED", "T-PACKED", "T-UPACKED", "T-COMP",
           "T-COMP5", "T-SCOMP5", "T-LONG", "T-SEP"]
MODES = {"A": "NEAREST-AWAY-FROM-ZERO", "Z": "NEAREST-TOWARD-ZERO", "E": "NEAREST-EVEN",
         "U": "AWAY-FROM-ZERO", "G": "TOWARD-GREATER", "L": "TOWARD-LESSER",
         "T": "TRUNCATION", "P": "PROHIBITED"}
OPS = ["C", "N", *MODES]


def interesting_values(rng: random.Random, n: int) -> list[Decimal]:
    """Random values biased toward the edges where implementations differ."""
    edges = [0, 1, -1, 9999, 10000, -10000, 32767, 32768, -32768, -32769, 65535,
             65536, 70000, 99999, 100000, 999999, 1000000, 2**31 - 1, 2**31, -(2**31),
             -(2**31) - 1, 2**32, 999999999999]
    out = [Decimal(e) for e in edges]
    out += [Decimal(e) + Decimal(f) for e in edges[:12]
            for f in ("0.5", "-0.5", "0.05", "0.005", "0.004", "0.995", "0.000001")]
    while len(out) < n:
        kind = rng.random()
        if kind < 0.3:  # ties at every scale the targets use
            places = rng.choice([1, 2, 3])
            whole = rng.randint(-99999, 99999)
            frac = rng.randint(0, 10 ** (places - 1) - 1) * 10 + 5
            value = Decimal(f"{abs(whole)}.{frac:0{places}d}")
            out.append(-value if whole < 0 else value)
        elif kind < 0.6:  # small, many decimals
            out.append(Decimal(rng.randint(-10**9, 10**9)).scaleb(-6))
        elif kind < 0.85:  # anywhere in the source's range
            out.append(Decimal(rng.randint(-(10**18) + 1, 10**18 - 1)).scaleb(-6))
        else:  # around binary capacities
            base = rng.choice([2**15, 2**16, 2**31, 2**32, 10**4, 10**5, 10**6])
            out.append(Decimal(rng.choice([1, -1]) * (base + rng.randint(-3, 3))))
    return out


@pytest.mark.skipif(shutil.which("cobc") is None, reason="GnuCOBOL not installed")
def test_python_stores_exactly_what_gnucobol_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("COBVIEW_CACHE", str(tmp_path / "cache"))
    layout = Layout.from_copybook(COBOL_DIR / "ARITHCASE.cpy")
    prog = cobview.Program.from_source(COBOL_DIR / "ARITH.cbl", using=[layout])
    case = cobview.view(bytearray(layout.size), layout)
    fields = [layout.find(t) for t in TARGETS]
    sentinel = {}
    for f in fields:
        case[f.name] = 7
        sentinel[f.name] = bytes(case.raw[f.offset:f.offset + f.size])
    options = layout.options

    mismatches = []
    checked = 0
    for value in interesting_values(random.Random(2026), 1500):
        case.AC_SOURCE = value
        source = case.AC_SOURCE  # as COBOL sees it: Decimal with 6 places
        for op in OPS:
            for f in fields:
                case[f.name] = 7
            case.AC_OP = op
            assert prog(case) == 0
            flags = case.AC_FLAGS
            for i, f in enumerate(fields):
                got = bytes(case.raw[f.offset:f.offset + f.size])
                with ExitStack() as stack:
                    if op in MODES:
                        stack.enter_context(cobview.rounded(MODES[op]))
                    if op == "N":
                        stack.enter_context(cobview.on_size_error("truncate"))
                    try:
                        want = cobview.codecs.encode(f, source, options, "cobol")
                        want_flag = "N"
                    except SizeError:
                        want, want_flag = sentinel[f.name], "Y"
                checked += 1
                if got != want or flags[i] != want_flag:
                    mismatches.append(
                        f"{op} {source} -> {f.name}: COBOL {got.hex()} flag {flags[i]}, "
                        f"cobview {want.hex()} flag {want_flag}"
                    )
    assert not mismatches, f"{len(mismatches)} of {checked} differ:\n" + "\n".join(mismatches[:15])
    assert checked == 1500 * len(OPS) * len(TARGETS)
