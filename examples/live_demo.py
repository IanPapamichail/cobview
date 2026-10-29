"""cobview v0.2: Python and COBOL working on the same memory.

COBOL writes 100,000 customers to a file.  Python memory-maps it and, for
the first 20,000, computes interest with COBOL rounding rules and hands
each record to a COBOL business rule (APPLYTXN) that posts it in place.
Run totals are read live from the program's EXTERNAL storage.

    python examples/live_demo.py
"""

import shutil
import subprocess
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import cobview

COBOL = Path(__file__).resolve().parent.parent / "cobol"
N, POSTED = 100_000, 20_000


class InactiveCustomer(cobview.ReturnCodeError):
    pass


class BalanceOverflow(cobview.ReturnCodeError):
    pass


def main() -> None:
    if shutil.which("cobc") is None:
        raise SystemExit("GnuCOBOL (cobc) is needed for this demo")
    work = Path(tempfile.mkdtemp(prefix="cobview-live-"))
    exe = work / "gendata"
    subprocess.run(["cobc", "-x", "-I", str(COBOL), "-o", str(exe), str(COBOL / "GENDATA.cbl")],
                   check=True)
    subprocess.run([str(exe), str(N), str(work / "c.dat"), str(work / "c.csv")],
                   check=True, capture_output=True)

    apply = cobview.Program.from_source(
        COBOL / "APPLYTXN.cbl", errors={4: InactiveCustomer, 8: BalanceOverflow}
    )
    print("signature read from the LINKAGE SECTION:")
    print("  ", apply.signature)
    stats = apply.external("TXN-STATS")  # COBOL EXTERNAL storage, live
    _, txn = apply.new_args(arithmetic="cobol")

    outcomes = {"posted": 0, "inactive": 0, "overflow": 0}
    first_message = None
    with cobview.open(work / "c.dat", apply.using[0], "r+", arithmetic="cobol") as customers:
        start = time.perf_counter()
        for cust in customers[:POSTED]:
            with cobview.rounded():  # ROUNDED MODE NEAREST-AWAY-FROM-ZERO
                txn.TXN_AMOUNT = abs(cust.CUST_BALANCE) * Decimal("0.035")
            try:
                apply.run(cust, txn, capture=True)
                outcomes["posted"] += 1
            except InactiveCustomer as err:
                outcomes["inactive"] += 1
                if first_message is None:
                    first_message = err.result.display[0]
            except BalanceOverflow:
                outcomes["overflow"] += 1
        elapsed = time.perf_counter() - start
        sample = customers[0]
        print(f"\n{POSTED:,} COBOL calls on a memory-mapped file: "
              f"{elapsed:.2f} s ({elapsed / POSTED * 1e6:.1f} us per record, incl. Python)")
        print("outcomes:", outcomes)
        print("first DISPLAY captured from COBOL:", first_message)
        print(f"customer 1 after interest: balance {sample.CUST_BALANCE}, visits {sample.CUST_VISITS}")

    print("\nrun totals, read from COBOL's EXTERNAL storage (no arguments passed):")
    print(f"   applied {stats.STAT_APPLIED:,} | rejected {stats.STAT_REJECTED:,} "
          f"| posted {stats.STAT_POSTED:,}")
    print(f"\nfiles in {work}")


if __name__ == "__main__":
    main()
