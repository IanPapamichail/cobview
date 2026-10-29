"""A tour of cobview v0.1.

Builds GENDATA.cbl with GnuCOBOL, lets COBOL write 100,000 customer
records, then reads and edits them from Python without copying.

    python examples/demo.py
"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

import cobview

HERE = Path(__file__).resolve().parent
COBOL = HERE.parent / "cobol"
N = 100_000


def main() -> None:
    if shutil.which("cobc") is None:
        raise SystemExit("GnuCOBOL (cobc) is needed for this demo")
    work = Path(tempfile.mkdtemp(prefix="cobview-"))
    exe = work / "gendata"
    subprocess.run(
        ["cobc", "-x", "-I", str(COBOL), "-o", str(exe), str(COBOL / "GENDATA.cbl")],
        check=True,
    )
    data = work / "customers.dat"
    subprocess.run([str(exe), str(N), str(data), str(work / "customers.csv")], check=True)

    layout = cobview.Layout.from_copybook(COBOL / "CUSTOMER.cpy")
    print("\n== layout from CUSTOMER.cpy ==")
    print(layout.describe())

    with cobview.open(data, layout, mode="r+") as recs:
        print(f"\n== {len(recs):,} records, {recs.buffer.nbytes:,} bytes, memory-mapped ==")
        rec = recs[9]
        print(rec)
        print("balance:", rec.CUST_BALANCE, "| monthly:", rec.MON_SPEND,
              "| active:", rec.CUST_ACTIVE)

        print("\n== write through the view; the file changes in place ==")
        rec.CUST_BALANCE = rec.CUST_BALANCE + 100
        rec.CUST_ACTIVE = True
        raw = bytes(rec.raw[26:31])
        print("new balance:", rec.CUST_BALANCE, "| packed bytes on disk:", raw.hex(" "))

        print("\n== whole columns with NumPy ==")
        t = time.perf_counter()
        points = recs.column("CUST-POINTS")
        print(f"CUST-POINTS (COMP, zero-copy view): {(time.perf_counter() - t) * 1e3:.2f} ms,"
              f" shares memory with the file: {np.shares_memory(points, np.asarray(recs.buffer))}")
        t = time.perf_counter()
        cents = recs.column("CUST-BALANCE", exact=True)
        print(f"CUST-BALANCE (COMP-3, vectorized decode): {(time.perf_counter() - t) * 1e3:.1f} ms")
        print(f"total balance: {cents.sum() / 100:,.2f}"
              f" | customers in debt: {(cents < 0).sum():,}")
        spend = recs.column("MON-SPEND")
        print("average monthly spend by month:", np.round(spend.mean(axis=0), 2))
        recs.flush()
    print(f"\nfiles left in {work}")


if __name__ == "__main__":
    main()
