"""COBOL writes, Python reads: the proof that layouts and codecs are right.

GENDATA.cbl writes binary CUSTOMER records and, alongside them, a CSV of
the same values formatted by COBOL itself.  Every field of every record
decoded by cobview must equal what COBOL printed.
"""

import csv
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

import cobview

COBOL_DIR = Path(__file__).resolve().parents[1] / "cobol"
N = 1000

pytestmark = pytest.mark.skipif(shutil.which("cobc") is None, reason="GnuCOBOL not installed")


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    work = tmp_path_factory.mktemp("cobol")
    exe = work / "gendata"
    subprocess.run(
        ["cobc", "-x", "-I", str(COBOL_DIR), "-o", str(exe), str(COBOL_DIR / "GENDATA.cbl")],
        check=True,
    )
    data, text = work / "customers.dat", work / "customers.csv"
    subprocess.run([str(exe), str(N), str(data), str(text)], check=True, capture_output=True)
    with text.open(newline="") as fh:
        rows = list(csv.reader(fh))
    return data, rows


def dec(s: str) -> Decimal:
    return Decimal(s.strip())


@pytest.fixture(scope="module")
def layout():
    return cobview.Layout.from_copybook(COBOL_DIR / "CUSTOMER.cpy")


def test_file_size_is_whole_records(generated, layout):
    data, rows = generated
    assert data.stat().st_size == N * layout.size
    assert len(rows) == N


def test_every_field_of_every_record(generated, layout):
    data, rows = generated
    with cobview.open(data, layout) as recs:
        assert len(recs) == N
        for rec, row in zip(recs, rows):
            assert rec.CUST_ID == int(row[0])
            assert rec.CUST_NAME == row[1]
            assert rec.CUST_BALANCE == dec(row[2])
            assert rec.CUST_CREDIT_LIM == dec(row[3])
            assert rec.CUST_VISITS == int(row[4])
            assert rec.CUST_POINTS == int(row[5])
            assert rec.CUST_RATE == float(dec(row[6]))
            assert list(rec.MON_SPEND) == [dec(row[7]), dec(row[8]), dec(row[9])]
            assert rec.CUST_STATUS == row[10]
            assert rec.CUST_ACTIVE == (row[10] == "A")
            assert rec.CUST_DATE_N == int(row[11])


def test_columns_match_record_by_record_values(generated, layout):
    data, rows = generated
    with cobview.open(data, layout) as recs:
        cents = recs.column("CUST-BALANCE", exact=True)
        assert cents.dtype == np.int64
        assert cents.tolist() == [int(dec(r[2]) * 100) for r in rows]
        assert np.allclose(recs.column("CUST-CREDIT-LIM"), [float(r[3]) for r in rows])
        assert recs.column("CUST-POINTS").tolist() == [int(r[5]) for r in rows]
        spend = recs.column("MON-SPEND", exact=True)
        assert spend.shape == (N, 3)
        assert spend[:, 2].tolist() == [int(dec(r[9]) * 100) for r in rows]
        assert recs.column("CUST-NAME").tolist() == [r[1] for r in rows]
        assert recs.column("CUST-DATE-N").tolist() == [int(r[11]) for r in rows]
        # zero-copy: the binary column points into the mapped file
        assert np.shares_memory(recs.column("CUST-POINTS"), np.asarray(recs.buffer))


def test_python_writes_cobol_reads(generated, layout, tmp_path):
    data, rows = generated
    copy = tmp_path / "edited.dat"
    copy.write_bytes(data.read_bytes())
    edits = {
        0: dict(CUST_NAME="HELLO FROM PYTHON",
                CUST_BALANCE=Decimal("-0.01"), CUST_CREDIT_LIM=Decimal("-99999.99")),
        1: dict(CUST_VISITS=0, CUST_POINTS=999999999, CUST_RATE=-2.5),
        2: dict(CUST_NAME="PYTHON WAS HERE", CUST_STATUS="I", CUST_DATE_N=19991231),
    }
    with cobview.open(copy, layout, "r+") as recs:
        for i, fields in edits.items():
            for name, value in fields.items():
                setattr(recs[i], name, value)
        recs[3].MON_SPEND = [Decimal("-1.00"), 0, Decimal("99999.99")]
        recs[4].CUST_ACTIVE = True
        recs[5].CUST_INACTIVE = True

    work = tmp_path / "readdata"
    subprocess.run(
        ["cobc", "-x", "-I", str(COBOL_DIR), "-o", str(work), str(COBOL_DIR / "READDATA.cbl")],
        check=True,
    )
    out = tmp_path / "edited.csv"
    subprocess.run([str(work), str(copy), str(out)], check=True)
    with out.open(newline="") as fh:
        back = list(csv.reader(fh))

    assert len(back) == N
    assert back[0][1] == edits[0]["CUST_NAME"]
    assert dec(back[0][2]) == Decimal("-0.01")
    assert dec(back[0][3]) == Decimal("-99999.99")
    assert int(back[1][4]) == 0 and int(back[1][5]) == 999999999
    assert dec(back[1][6]) == Decimal("-2.5")
    assert back[2][1] == "PYTHON WAS HERE" and back[2][10] == "I"
    assert back[2][11] == "19991231"
    assert [dec(x) for x in back[3][7:10]] == [Decimal("-1.00"), 0, Decimal("99999.99")]
    assert back[4][10] == "A" and back[5][10] == "I"
    # everything Python did not touch is byte-for-byte what COBOL wrote
    assert back[6:] == rows[6:]


def test_negative_zoned_and_extremes_are_present(generated, layout):
    # make sure the data actually exercises the tricky encodings
    data, rows = generated
    raw = data.read_bytes()
    credit = [raw[i * 73 + 37] for i in range(N)]
    assert any(0x70 <= b <= 0x79 for b in credit)  # GnuCOBOL negative overpunch
    assert rows[-1][2].strip() == "-9999999.99"
