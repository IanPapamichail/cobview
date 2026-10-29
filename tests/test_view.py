import ctypes
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

import cobview
from cobview import CobolDataError, Layout

COBOL_DIR = Path(__file__).resolve().parents[1] / "cobol"


@pytest.fixture
def layout():
    return Layout.from_copybook(COBOL_DIR / "CUSTOMER.cpy")


def blank(layout, n=1):
    """n records of valid zero values, built through the view itself."""
    buf = bytearray(layout.size * n)
    for rec in cobview.records(buf, layout):
        rec.CUST_ID = 0
        rec.CUST_NAME = ""
        rec.CUST_BALANCE = 0
        rec.CUST_CREDIT_LIM = 0
        rec.CUST_VISITS = 0
        rec.CUST_POINTS = 0
        rec.CUST_RATE = 0
        rec.MON_SPEND = [0, 0, 0]
        rec.CUST_STATUS = "I"
        rec.CUST_DATE_N = 20000101
    return buf


def test_write_then_read_every_type(layout):
    buf = blank(layout)
    rec = cobview.view(buf, layout)
    rec.CUST_ID = 42
    rec.cust_name = "ADA LOVELACE"
    rec.CUST_BALANCE = Decimal("-1234.56")
    rec.CUST_CREDIT_LIM = "500.25"
    rec.CUST_VISITS = 9999
    rec.CUST_POINTS = -7
    rec.CUST_RATE = 0.5
    rec.CUST_MONTHLY[2].MON_SPEND = Decimal("-0.01")
    rec.CUST_ACTIVE = True
    rec.CUST_DATE.CD_YYYY = 2026

    assert rec.CUST_ID == 42
    assert rec.CUST_NAME == "ADA LOVELACE"
    assert rec.CUST_BALANCE == Decimal("-1234.56")
    assert rec.CUST_CREDIT_LIM == Decimal("500.25")
    assert rec.CUST_VISITS == 9999
    assert rec.CUST_POINTS == -7
    assert rec.CUST_RATE == 0.5
    assert rec.MON_SPEND[2] == Decimal("-0.01")
    assert rec.CUST_STATUS == "A" and rec.CUST_ACTIVE and not rec.CUST_INACTIVE
    assert rec.CUST_DATE_N == 20260101  # REDEFINES sees the same bytes
    # bytes land exactly where COBOL expects them
    assert bytes(buf[0:6]) == b"000042"
    assert bytes(buf[26:31]) == bytes.fromhex("000123456d")
    assert bytes(buf[38:40]) == (9999).to_bytes(2, "little")
    assert bytes(buf[40:44]) == (-7).to_bytes(4, "big", signed=True)


def test_views_are_zero_copy_both_ways(layout):
    buf = blank(layout, 2)
    recs = cobview.records(buf, layout)
    second = recs[1]
    # change the buffer underneath: the view sees it
    buf[73:79] = b"000777"
    assert second.CUST_ID == 777
    # change through the view: the buffer sees it
    second.CUST_ID = 5
    assert bytes(buf[73:79]) == b"000005"
    # a NumPy column of a binary field is the same memory
    points = recs.column("CUST-POINTS")
    assert np.shares_memory(points, np.frombuffer(buf, dtype=np.uint8))
    points[0] = 123456
    assert recs[0].CUST_POINTS == 123456


def test_works_over_ctypes_memory(layout):
    # the same mechanism v0.2 uses to share live COBOL storage
    mem = (ctypes.c_ubyte * layout.size).from_buffer_copy(blank(layout))
    rec = cobview.view(mem, layout)
    rec.CUST_BALANCE = 99
    assert bytes(mem)[26:31] == b"\x00\x00\x09\x90\x0c"


def test_errors_are_specific(layout):
    buf = blank(layout)
    rec = cobview.view(buf, layout)
    with pytest.raises(CobolDataError, match="does not fit"):
        rec.CUST_VISITS = 10000
    with pytest.raises(CobolDataError, match="decimal places"):
        rec.CUST_BALANCE = Decimal("1.001")
    with pytest.raises(CobolDataError, match="bytes do not fit"):
        rec.CUST_NAME = "X" * 21
    with pytest.raises(AttributeError, match="no field"):
        rec.NOPE
    with pytest.raises(ValueError, match="only be set to True"):
        rec.CUST_ACTIVE = False
    buf[26] = 0xAB  # corrupt the packed field
    with pytest.raises(CobolDataError, match="CUST-BALANCE"):
        rec.CUST_BALANCE


def test_read_only_buffers_refuse_writes(layout):
    rec = cobview.view(bytes(blank(layout)), layout)
    with pytest.raises(TypeError, match="read-only"):
        rec.CUST_ID = 1


def test_partial_record_buffer_is_rejected(layout):
    with pytest.raises(CobolDataError, match="left over"):
        cobview.records(bytes(layout.size + 1), layout)


def test_record_file_mode_r_plus_writes_to_disk(tmp_path, layout):
    path = tmp_path / "c.dat"
    path.write_bytes(bytes(blank(layout, 3)))
    with cobview.open(path, layout, "r+") as recs:
        recs[2].CUST_NAME = "ON DISK"
    with cobview.open(path, layout) as recs:
        assert recs[2].CUST_NAME == "ON DISK"
        with pytest.raises(TypeError, match="read-only"):
            recs[0].CUST_ID = 1


def test_slices_and_negative_indexes(layout):
    buf = blank(layout, 5)
    recs = cobview.records(buf, layout)
    for i, rec in enumerate(recs):
        rec.CUST_ID = i
    assert [r.CUST_ID for r in recs[1:4]] == [1, 2, 3]
    assert recs[-1].CUST_ID == 4
    assert len(recs[3:1]) == 0


def test_nested_occurs():
    layout = Layout.from_copybook(
        """
       01 GRID.
          05 ROW OCCURS 3 TIMES.
             10 CELL PIC S9(3) COMP-3 OCCURS 4 TIMES.
        """
    )
    buf = bytearray(layout.size)
    rec = cobview.view(buf, layout)
    for r in range(3):
        rec.ROW[r].CELL = [r * 10 + c for c in range(4)]
    assert rec.ROW[2].CELL[3] == 23
    assert rec.CELL[1][2] == 12  # unqualified: indexes for every OCCURS level
    col = cobview.records(buf, layout).column("CELL")
    assert col.shape == (1, 3, 4)
    assert col[0, 2, 3] == 23


def test_to_dict_skips_redefines_by_default(layout):
    rec = cobview.view(blank(layout), layout)
    d = rec.to_dict()
    assert "CUST-DATE-N" not in d and d["CUST-DATE"]["CD-YYYY"] == 2000
    assert rec.to_dict(redefines=True)["CUST-DATE-N"] == 20000101


def test_ebcdic_layout_round_trip():
    layout = Layout.from_copybook(
        "01 R.\n 05 NAME PIC X(5).\n 05 AMT PIC S9(3)V99.\n 05 PK PIC S9(3) COMP-3.\n",
        options=cobview.Options.ibm(),
    )
    buf = bytearray(layout.size)
    rec = cobview.view(buf, layout)
    rec.NAME = "HI"
    rec.AMT = Decimal("-1.50")
    rec.PK = 12
    assert bytes(buf[:5]) == "HI   ".encode("cp037")
    assert bytes(buf[5:10]) == b"\xf0\xf0\xf1\xf5\xd0"
    assert (rec.NAME, rec.AMT, rec.PK) == ("HI", Decimal("-1.50"), 12)
    recs = cobview.records(buf, layout)
    assert recs.column("AMT")[0] == -1.5
    assert recs.column("NAME")[0] == "HI"
