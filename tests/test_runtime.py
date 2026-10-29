"""Calling COBOL programs in-process on Python-owned memory."""

import ctypes
import os
import shutil
import subprocess
import sys
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

import cobview
from cobview import CobolError, CompileError, Layout

ROOT = Path(__file__).resolve().parents[1]
COBOL_DIR = ROOT / "cobol"

pytestmark = pytest.mark.skipif(shutil.which("cobc") is None, reason="GnuCOBOL not installed")


@pytest.fixture(autouse=True)
def cache(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("COBVIEW_CACHE", str(tmp_path_factory.getbasetemp() / "cobview-cache"))


@pytest.fixture(scope="module")
def customer():
    return Layout.from_copybook(COBOL_DIR / "CUSTOMER.cpy")


@pytest.fixture(scope="module")
def txn():
    return Layout.from_copybook(COBOL_DIR / "TXN.cpy")


def write(tmp_path, name, body):
    """Write fixed-format COBOL: dedent the snippet, then start it in column 8."""
    path = tmp_path / name
    path.write_text(textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 7) + "\n")
    return path


def make_customer(layout, active=True, balance="100.00"):
    rec = cobview.view(bytearray(layout.size), layout)
    rec.CUST_ID = 1
    rec.CUST_NAME = "ADA"
    rec.CUST_BALANCE = Decimal(balance)
    rec.CUST_CREDIT_LIM = 0
    rec.CUST_VISITS = 0
    rec.CUST_POINTS = 0
    rec.CUST_RATE = 0
    rec.MON_SPEND = [0, 0, 0]
    rec.CUST_STATUS = "A" if active else "I"
    rec.CUST_DATE_N = 20260101
    return rec


@pytest.fixture(scope="module")
def applytxn(customer, txn, tmp_path_factory):
    os.environ["COBVIEW_CACHE"] = str(tmp_path_factory.getbasetemp() / "cobview-cache")
    return cobview.Program.from_source(COBOL_DIR / "APPLYTXN.cbl", using=[customer, txn])


def test_cobol_edits_python_memory_in_place(applytxn, customer, txn):
    cust = make_customer(customer)
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = Decimal("25.50")
    assert applytxn(cust, t) == 0
    assert cust.CUST_BALANCE == Decimal("125.50")
    assert cust.CUST_VISITS == 1
    assert t.TXN_APPLIED


def test_working_storage_persists_until_cancel(applytxn, customer, txn):
    cust = make_customer(customer)
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = 1
    applytxn.cancel()
    counts = []
    for _ in range(3):
        applytxn(cust, t)
        counts.append(t.TXN_COUNT)
    assert counts == [1, 2, 3]
    applytxn.cancel()
    applytxn(cust, t)
    assert t.TXN_COUNT == 1


def test_business_rules_report_through_return_code(applytxn, customer, txn):
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = 1
    assert applytxn(make_customer(customer, active=False), t) == 4
    assert t.TXN_INACTIVE
    t.TXN_AMOUNT = Decimal("9999999.99")
    rich = make_customer(customer, balance="9999999.99")
    assert applytxn(rich, t) == 8
    assert t.TXN_OVERFLOW
    assert rich.CUST_BALANCE == Decimal("9999999.99")  # COBOL left it unchanged


def test_records_in_a_memory_mapped_file(applytxn, customer, txn, tmp_path):
    data = tmp_path / "c.dat"
    data.write_bytes(bytes(make_customer(customer).raw) * 4)
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = 10
    with cobview.open(data, customer, "r+") as recs:
        for rec in recs:
            applytxn(rec, t)
    with cobview.open(data, customer) as recs:
        assert [r.CUST_BALANCE for r in recs] == [Decimal("110.00")] * 4


def test_ctypes_and_bytearray_arguments(customer, txn, applytxn):
    cust = (ctypes.c_char * customer.size).from_buffer_copy(bytes(make_customer(customer).raw))
    t = bytearray(txn.size)
    tv = cobview.view(t, txn)
    tv.TXN_AMOUNT = 5
    assert applytxn(cust, t) == 0
    assert cobview.view(cust, customer).CUST_BALANCE == Decimal("105.00")


def test_arguments_are_checked_before_cobol_runs(applytxn, customer, txn):
    cust = make_customer(customer)
    with pytest.raises(TypeError, match="takes 2 arguments"):
        applytxn(cust)
    with pytest.raises(ValueError, match="needs"):
        applytxn(cust, bytearray(2))
    with pytest.raises(TypeError, match="read-only"):
        applytxn(cust, bytes(txn.size))
    with pytest.raises(TypeError, match="read-only"):
        applytxn(cobview.view(bytes(cust.raw), customer), bytearray(txn.size))


def test_compile_cache_and_errors(tmp_path):
    src = write(tmp_path, "HELLO.cbl", """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. HELLO.
           PROCEDURE DIVISION.
               MOVE 3 TO RETURN-CODE
               GOBACK.
    """)
    first = cobview.compile(src)
    assert cobview.compile(src) == first  # cached by content
    assert cobview.Program(first, "HELLO")() == 3
    bad = write(tmp_path, "BAD.cbl", """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. BAD.
           PROCEDURE DIVISION.
               MOVE TO.
    """)
    with pytest.raises(CompileError) as err:
        cobview.compile(bad)
    assert "BAD.cbl" in str(err.value) and err.value.stderr


def test_program_names_are_global_like_in_cobol(tmp_path):
    (tmp_path / "a").mkdir()
    a = write(tmp_path / "a", "TWIN.cbl", """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. TWIN.
           PROCEDURE DIVISION.
               MOVE 1 TO RETURN-CODE
               GOBACK.
    """)
    (tmp_path / "b").mkdir()
    b = tmp_path / "b" / "TWIN.cbl"
    b.write_text(a.read_text().replace("MOVE 1", "MOVE 2"))
    assert cobview.Program.from_source(a)() == 1
    with pytest.raises(CobolError, match="global"):
        cobview.Program.from_source(b)


def test_stop_run_is_turned_into_goback(tmp_path):
    src = write(tmp_path, "QUITTER.cbl", """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. QUITTER.
           PROCEDURE DIVISION.
               STOP RUN RETURNING 4.
    """)
    prog = cobview.Program.from_source(src)
    assert prog() == 4
    assert prog() == 4  # the runtime is still alive


# -- behaviour that ends the COBOL runtime runs in a separate interpreter -------


def run_isolated(tmp_path, code: str) -> subprocess.CompletedProcess:
    script = tmp_path / "isolated.py"
    script.write_text(textwrap.dedent(code))
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          env=env, cwd=tmp_path, timeout=120)


def test_real_stop_run_becomes_an_exception_not_an_exit(tmp_path):
    write(tmp_path, "ENDER.cbl", """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. ENDER.
           PROCEDURE DIVISION.
               STOP RUN RETURNING 5.
    """)
    proc = run_isolated(tmp_path, """
        import cobview
        prog = cobview.Program.from_source("ENDER.cbl", stop_run="keep")
        try:
            prog()
        except cobview.CobolStopRun as e:
            print("stop", e.exit_code)
        try:
            prog()
        except cobview.CobolError as e:
            print("refused")
        print("python still running")
    """)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["stop", "5", "refused", "python", "still", "running"]


def test_runtime_error_becomes_an_exception(tmp_path):
    write(tmp_path, "BROKEN.cbl", """
           IDENTIFICATION DIVISION.
           PROGRAM-ID. BROKEN.
           PROCEDURE DIVISION.
               CALL "NO-SUCH-PROGRAM"
               GOBACK.
    """)
    proc = run_isolated(tmp_path, """
        import cobview
        try:
            cobview.Program.from_source("BROKEN.cbl")()
        except cobview.CobolRuntimeError:
            print("runtime error caught")
    """)
    assert proc.returncode == 0, proc.stderr
    assert "runtime error caught" in proc.stdout
    assert "NO-SUCH-PROGRAM" in proc.stderr  # libcob's own message is kept


def test_ctrl_c_still_reaches_python(tmp_path):
    proc = run_isolated(tmp_path, """
        import os, signal, time, cobview
        cobview.Runtime.get()  # cob_init installs C signal handlers...
        try:
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(1)
        except KeyboardInterrupt:
            print("KeyboardInterrupt")  # ...which cobview put back
    """)
    assert proc.returncode == 0, proc.stderr
    assert "KeyboardInterrupt" in proc.stdout


# -- v0.2 extras ---------------------------------------------------------------


class Inactive(cobview.ReturnCodeError):
    pass


class Overflow(ValueError):
    pass


def test_signature_comes_from_the_linkage_section(applytxn, customer, txn):
    assert str(applytxn.signature) == "APPLYTXN USING CUSTOMER-REC (73 bytes), TXN-REC (10 bytes)"
    assert [l.size for l in applytxn.using] == [73, 10]
    cust, t = applytxn.new_args()
    assert cust.layout.name == "CUSTOMER-REC" and t.layout.name == "TXN-REC"
    assert {f.name for f in cust.layout.fields()} == {f.name for f in customer.fields()}


def test_new_args_are_ready_to_fill(applytxn):
    cust, t = applytxn.new_args(arithmetic="cobol")
    cust.CUST_STATUS = "A"
    cust.CUST_BALANCE = 0
    cust.CUST_VISITS = 0
    t.TXN_AMOUNT = Decimal("12.345")  # cobol arithmetic: truncated to 12.34
    assert applytxn(cust, t) == 0
    assert cust.CUST_BALANCE == Decimal("12.34")


def test_external_storage_is_shared_by_name(applytxn, customer, txn):
    stats = applytxn.external("TXN-STATS")
    assert stats.layout.size == 4 + 4 + 7
    before = (stats.STAT_APPLIED, stats.STAT_POSTED)
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = Decimal("2.50")
    for _ in range(4):
        applytxn(make_customer(customer), t)
    assert stats.STAT_APPLIED == before[0] + 4
    assert stats.STAT_POSTED == before[1] + Decimal("10.00")
    # Python can write it too, and COBOL carries on from there
    stats.STAT_APPLIED = 1000
    applytxn(make_customer(customer), t)
    assert stats.STAT_APPLIED == 1001
    # the module-level function reaches the same bytes
    same = cobview.external("TXN-STATS", stats.layout)
    assert same.STAT_APPLIED == 1001


def test_external_size_mismatch_is_caught_before_libcob(applytxn):
    applytxn.external("TXN-STATS")
    wrong = Layout.from_copybook("01 TXN-STATS.\n 05 X PIC X(99).\n")
    with pytest.raises(CobolError, match="15 bytes"):
        cobview.external("TXN-STATS", wrong)


def test_display_output_is_captured(applytxn, customer, txn, capfd):
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = 1
    result = applytxn.run(make_customer(customer, active=False), t, capture=True)
    assert result.return_code == 4
    assert result.display == ["APPLYTXN: customer 000001 is inactive"]
    assert "inactive" not in capfd.readouterr().out
    # without capture it goes to the terminal as usual
    applytxn(make_customer(customer, active=False), t)
    assert "inactive" in capfd.readouterr().out


def test_return_codes_become_exceptions(customer, txn, applytxn):
    prog = cobview.Program.from_source(COBOL_DIR / "APPLYTXN.cbl",
                                       errors={4: Inactive, 8: Overflow})
    t = cobview.view(bytearray(txn.size), txn)
    t.TXN_AMOUNT = 1
    with pytest.raises(Inactive) as err:
        prog.run(make_customer(customer, active=False), t, capture=True)
    assert err.value.return_code == 4
    assert err.value.result.display == ["APPLYTXN: customer 000001 is inactive"]
    t.TXN_AMOUNT = Decimal("9999999.99")
    with pytest.raises(Overflow) as err:
        prog(make_customer(customer, balance="9999999.99"), t)
    assert err.value.return_code == 8
    t.TXN_AMOUNT = 1
    assert prog(make_customer(customer), t) == 0

    strict = cobview.Program.from_source(COBOL_DIR / "APPLYTXN.cbl", errors="nonzero")
    with pytest.raises(cobview.ReturnCodeError, match="RETURN-CODE 4"):
        strict(make_customer(customer, active=False), t)
    with pytest.raises(TypeError):
        cobview.Program.from_source(COBOL_DIR / "APPLYTXN.cbl", errors={4: "oops"})


def test_captured_runtime_error_carries_libcob_message(tmp_path):
    write(tmp_path, "BROKEN2.cbl", """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. BROKEN2.
        PROCEDURE DIVISION.
            CALL "NO-SUCH-PROGRAM"
            GOBACK.
    """)
    proc = run_isolated(tmp_path, """
        import cobview
        try:
            cobview.Program.from_source("BROKEN2.cbl").run(capture=True)
        except cobview.CobolRuntimeError as e:
            print("MESSAGE:", e)
    """)
    assert proc.returncode == 0, proc.stderr
    assert "NO-SUCH-PROGRAM" in proc.stdout
