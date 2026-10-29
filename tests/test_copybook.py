from pathlib import Path

import pytest

from cobview import CopybookError, Layout, Options

COBOL_DIR = Path(__file__).resolve().parents[1] / "cobol"


def offsets(layout):
    return {f.name: (f.offset, f.size) for f in layout.fields()}


def test_customer_layout_matches_gnucobol():
    # Offsets confirmed against a hex dump of GnuCOBOL 3.2 output.
    layout = Layout.from_copybook(COBOL_DIR / "CUSTOMER.cpy")
    assert layout.size == 73
    o = offsets(layout)
    assert o["CUST-ID"] == (0, 6)
    assert o["CUST-NAME"] == (6, 20)
    assert o["CUST-BALANCE"] == (26, 5)
    assert o["CUST-CREDIT-LIM"] == (31, 7)
    assert o["CUST-VISITS"] == (38, 2)
    assert o["CUST-POINTS"] == (40, 4)
    assert o["CUST-RATE"] == (44, 8)
    assert o["CUST-MONTHLY"] == (52, 4)
    assert o["MON-SPEND"] == (52, 4)
    assert o["CUST-STATUS"] == (64, 1)
    assert o["CUST-DATE"] == (65, 8)
    assert o["CUST-DATE-N"] == (65, 8)
    assert layout.find("MON-SPEND").dims == ((3, 4),)
    assert layout.condition("CUST-ACTIVE")[1] == ["A"]


def test_free_format_and_fragment_without_01():
    layout = Layout.from_copybook(
        "05 A PIC X(3).\n05 B PIC S9(3)V9 COMP-3. *> comment\n05 C PIC 9(2).\n"
    )
    assert layout.size == 3 + 3 + 2
    assert layout.find("B").scale == 1
    assert layout.find("C").offset == 6


def test_group_usage_is_inherited():
    layout = Layout.from_copybook(
        """
       01 R.
          05 AMOUNTS COMP-3.
             10 A PIC S9(5).
             10 B PIC S9(7)V99.
          05 C PIC X.
        """
    )
    assert layout.find("A").kind == "packed" and layout.find("A").size == 3
    assert layout.find("B").size == 5
    assert layout.find("C").offset == 8


def test_nested_occurs_dims_and_strides():
    layout = Layout.from_copybook(
        """
       01 GRID.
          05 ROW OCCURS 3 TIMES INDEXED BY R-IX.
             10 CELL PIC 9(2) OCCURS 4 TIMES.
             10 ROW-TOTAL PIC 9(4).
          05 TAIL PIC X.
        """
    )
    cell = layout.find("CELL")
    assert cell.dims == ((3, 12), (4, 2))
    assert layout.find("ROW-TOTAL").offset == 8
    assert layout.find("TAIL").offset == 36
    assert layout.size == 37


def test_redefines_takes_the_larger_size():
    layout = Layout.from_copybook(
        """
       01 R.
          05 A PIC X(4).
          05 B REDEFINES A PIC 9(4).
          05 C PIC X.
        """
    )
    assert layout.find("B").offset == 0
    assert layout.find("C").offset == 4


def test_binary_sizes_follow_options():
    text = "01 R.\n 05 A PIC 9(2) COMP.\n 05 B PIC 9(4) COMP.\n 05 C PIC 9(10) COMP.\n"
    gnu = Layout.from_copybook(text)
    ibm = Layout.from_copybook(text, options=Options.ibm())
    assert [f.size for f in gnu.elementary()] == [1, 2, 8]
    assert [f.size for f in ibm.elementary()] == [2, 2, 8]
    assert ibm.options.ebcdic and not gnu.options.ebcdic


def test_sign_separate_adds_a_byte():
    layout = Layout.from_copybook(
        "01 R.\n 05 A PIC S9(4) SIGN IS LEADING SEPARATE CHARACTER.\n 05 B PIC X.\n"
    )
    a = layout.find("A")
    assert a.size == 5 and a.sign_leading and a.sign_separate
    assert layout.find("B").offset == 5


def test_qualified_names_and_ambiguity():
    layout = Layout.from_copybook(
        """
       01 R.
          05 HOME.
             10 CITY PIC X(10).
          05 WORK.
             10 CITY PIC X(10).
        """
    )
    with pytest.raises(KeyError, match="ambiguous"):
        layout.find("CITY")
    assert layout.find("CITY OF WORK").offset == 10
    assert layout.find("HOME.CITY").offset == 0
    assert layout.find("city in home").offset == 0


def test_88_values_with_thru():
    layout = Layout.from_copybook(
        "01 R.\n 05 GRADE PIC 9.\n  88 PASSED VALUES ARE 5 THRU 9.\n  88 TOP VALUE 9.\n"
    )
    grade = layout.find("GRADE")
    assert grade.conditions == {"PASSED": [(5, 9)], "TOP": [9]}


@pytest.mark.parametrize(
    "text, message",
    [
        ("01 R.\n 05 N PIC 9.\n 05 T PIC X OCCURS 1 TO 5 DEPENDING ON N.\n", "DEPENDING"),
        ("01 R.\n 05 A PIC S9(4) COMP SYNC.\n", "SYNCHRONIZED"),
        ("01 R.\n 05 A PIC N(4).\n", "national"),
        ("01 R.\n 05 A PIC X(4)\n", "period"),
        ("01 R.\n 05 A.\n", "no PIC"),
        ("01 R.\n 05 B REDEFINES A PIC X.\n", "REDEFINES"),
        ("01 R.\n 05 A PIC 9P.\n", "P scaling"),
    ],
)
def test_unsupported_or_bad_copybooks_fail_loudly(text, message):
    with pytest.raises(CopybookError, match=message):
        Layout.from_copybook(text)


def test_missing_copybook_path_is_a_file_error():
    with pytest.raises(FileNotFoundError):
        Layout.from_copybook("does/not/exist.cpy")


def test_describe_lists_every_field():
    layout = Layout.from_copybook(COBOL_DIR / "CUSTOMER.cpy")
    table = layout.describe()
    for f in layout.fields():
        assert f.name in table
    assert "record size: 73 bytes" in table
