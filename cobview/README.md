# cobview

Zero-copy, copybook-typed views over COBOL data in Python, and in-process
calls into COBOL programs on that same memory.

Point cobview at a copybook and a buffer (a data file, a `bytearray`, a
`mmap`, ctypes memory shared with a running COBOL program) and read or
write fields by name. Nothing is copied: reading a field decodes just
those bytes, and assigning to a field encodes the value straight back
into the same memory, where COBOL sees it.

```python
import cobview

layout = cobview.Layout.from_copybook("cobol/CUSTOMER.cpy")

with cobview.open("customers.dat", layout, mode="r+") as recs:
    rec = recs[9]
    rec.CUST_BALANCE            # Decimal('123456.70')   (COMP-3)
    rec.MON_SPEND               # [Decimal('31.30'), Decimal('-62.60'), Decimal('93.90')]
    rec.CUST_ACTIVE             # False                  (88-level condition)

    rec.CUST_BALANCE += 100     # written into the file, packed, in place
    rec.CUST_ACTIVE = True      # sets CUST-STATUS to "A"

    cents = recs.column("CUST-BALANCE", exact=True)   # NumPy int64, vectorized
    points = recs.column("CUST-POINTS")               # zero-copy NumPy view
```

## Why

COBOL stores most numbers as packed decimal (`COMP-3`) or zoned decimal
(`PIC 9` DISPLAY). Neither exists in Python's buffer protocol or NumPy,
so existing tools convert whole files to JSON or dicts first. cobview
keeps the original bytes and decodes lazily, field by field, or a whole
column at a time with vectorized NumPy.

## Calling COBOL from Python (v0.2)

```python
apply = cobview.Program.from_source("cobol/APPLYTXN.cbl",
                                    errors={4: InactiveCustomer, 8: BalanceOverflow})
apply.signature        # APPLYTXN USING CUSTOMER-REC (73 bytes), TXN-REC (10 bytes)
cust, txn = apply.new_args(arithmetic="cobol")   # typed by the LINKAGE SECTION

with cobview.open("customers.dat", apply.using[0], "r+") as customers:
    for cust in customers:
        txn.TXN_AMOUNT = 25
        apply(cust, txn)               # COBOL edits the mapped file in place

stats = apply.external("TXN-STATS")    # the program's EXTERNAL storage, live
result = apply.run(cust, txn, capture=True)
result.display                         # what the program DISPLAYed
```

* **In-process, zero-copy.** Python owns the memory; the COBOL program gets
  its address BY REFERENCE through its LINKAGE SECTION, as if another
  COBOL program had CALLed it. About 4 µs per call.
* **Signature from source.** `from_source` compiles (cached by content),
  then reads `PROCEDURE DIVISION USING` and the LINKAGE SECTION, `COPY`
  statements included, so arguments are size-checked before COBOL touches
  them and `new_args()` can allocate them.
* **WORKING-STORAGE persists** between calls, as in COBOL; `cancel()`
  resets it (`CANCEL`).
* **EXTERNAL storage** is shared by name across the run unit;
  `cobview.external(name, layout)` / `Program.external(name)` give a live
  view of it with no arguments passed. Size mismatches are caught in
  Python, because libcob would end the process.
* **RETURN-CODE → exceptions** with `errors={code: ExceptionClass}` or
  `errors="nonzero"`.
* **DISPLAY capture** with `run(..., capture=True)`.
* **Safe embedding.** libcob's signal handlers are removed again so Ctrl-C
  still works; `STOP RUN` and runtime errors become `CobolStopRun` /
  `CobolRuntimeError` instead of ending Python. `compile()` also inserts
  COBOL's own `REPLACE ==STOP RUN== BY ==GOBACK==.` so legacy programs
  can be embedded unchanged (`stop_run="keep"` to opt out).
* **Program names are global**, as in a COBOL run unit: loading a second
  module with the same PROGRAM-ID is refused instead of silently calling
  the first one.

## COBOL arithmetic (v0.2)

```python
rec = cobview.view(buf, layout, arithmetic="cobol")
rec.AMOUNT = Decimal("1.239")          # 1.23: truncation, like COMPUTE
with cobview.rounded():                # ROUNDED (NEAREST-AWAY-FROM-ZERO)
    rec.AMOUNT = Decimal("1.235")      # 1.24
with cobview.rounded("NEAREST-EVEN"):
    rec.AMOUNT = Decimal("1.245")      # 1.24
rec.COUNT = 12345                      # PIC 9(4): SizeError, field unchanged
with cobview.on_size_error("truncate"):
    rec.COUNT = 12345                  # 2345, like COMPUTE without ON SIZE ERROR
```

The default, `arithmetic="strict"`, never loses data silently. With
`arithmetic="cobol"`, assignment follows GnuCOBOL's `COMPUTE` byte for
byte, including details that are easy to get wrong:

* all eight `ROUNDED MODE`s of COBOL 2014;
* negative values in unsigned fields keep their absolute value;
* `COMP` is limited by its PIC digits, `COMP-5` / `BINARY-LONG` by the
  size of the binary (and they wrap when truncated);
* signed binaries treat the most negative value (-32768) as a size error;
* high-order truncation can leave a *negative zero* in packed and zoned
  fields;
* `ROUNDED MODE IS PROHIBITED` judges the decimal places a value carries
  (`1.250` into `V99` is a size error, `0` never is).

These rules are not guessed: `tests/test_arithmetic.py` sends 1,500
random and edge-case values through `cobol/ARITH.cbl` with every
statement form into nine kinds of field, and compares cobview's bytes with
GnuCOBOL's: 135,000 comparisons, no differences.

## What the views support

| COBOL                                   | Python value                    | Column (NumPy)            |
|-----------------------------------------|---------------------------------|---------------------------|
| `PIC X(n)`, numeric-edited              | `str` (trailing spaces removed) | `str` array               |
| `PIC S9(n)V9(m)` DISPLAY (zoned)        | `int` / `Decimal`               | vectorized decode         |
| `COMP-3` / `PACKED-DECIMAL`             | `int` / `Decimal`               | vectorized decode         |
| `COMP` / `BINARY` / `COMP-4` / `COMP-5` | `int` / `Decimal`               | **zero-copy** view        |
| `BINARY-CHAR/SHORT/LONG/DOUBLE`         | `int`                           | **zero-copy** view        |
| `COMP-1` / `COMP-2`                     | `float`                         | **zero-copy** view        |
| groups, `OCCURS n` (nested), `REDEFINES`| nested views / lists            | extra array dimensions    |
| 88-level conditions (incl. `THRU`)      | `bool`, settable to `True`      |                           |
| `SIGN LEADING/TRAILING [SEPARATE]`      | yes                             | yes                       |
| EBCDIC (`Options.ibm()`)                | yes (except COMP-1/2)           | yes                       |

Defaults match GnuCOBOL (`binary-size: 1-2-4-8`, big-endian `COMP`,
native `COMP-5`). Use `Options.ibm()` for IBM mainframe data.

By default, values that do not fit or would lose decimal places raise
(`SizeError` / `CobolDataError`) instead of being truncated silently.

Not yet supported (fails with a clear `CopybookError`): `OCCURS DEPENDING
ON`, `SYNCHRONIZED`, `PIC P`, national (`PIC N`), level 66 `RENAMES`,
continuation lines, IBM hex floating point. Calling COBOL: `BY VALUE`
parameters, nested calls (COBOL calling back into Python).

## Proof against real COBOL

`cobol/GENDATA.cbl` writes binary records plus a CSV of the same values
formatted by COBOL. The tests decode all 1,000 records with cobview and
compare every field. `cobol/READDATA.cbl` goes the other way: Python
edits a file and COBOL reads it back. `cobol/ARITH.cbl` is the reference
for the arithmetic rules, and `cobol/APPLYTXN.cbl` is a business rule
called in-process.

## Running

```bash
pip install -e ".[test]"
pytest                     # COBOL tests need GnuCOBOL (cobc); skipped otherwise
python examples/demo.py       # v0.1 tour: views and columns (needs cobc)
python examples/live_demo.py  # v0.2: Python and COBOL on the same memory
```

GnuCOBOL: `apt install gnucobol` (Debian/Ubuntu) or `brew install gnucobol` (macOS).

## Performance (1,000,000 records, 73 MB)

| operation                                   | time      |
|---------------------------------------------|-----------|
| binary column (zero-copy view)              | < 1 ms    |
| zoned column, vectorized                    | ~110 ms   |
| packed column, vectorized                   | ~300 ms   |
| packed field read record by record (Python) | ~3.7 s    |
| in-process COBOL call (tiny program)        | ~4 µs     |

## Roadmap

- ~~v0.1 views, codecs, NumPy columns~~
- ~~v0.2 in-process calls, COBOL arithmetic, EXTERNAL, signatures, DISPLAY capture~~
- **v0.3** COBOL calling Python (callbacks / Python as a subprogram), watching a separate COBOL
  job through a shared mapping, `MOVE` semantics, column writes, `OCCURS DEPENDING ON`
- **v0.4** Rust/Cython codecs and benchmarks

## Layout

```
src/cobview/copybook.py   copybook parser -> byte layout
src/cobview/codecs.py     encode/decode one value
src/cobview/view.py       Record / Records / RecordFile views
src/cobview/columns.py    NumPy column access
src/cobview/arithmetic.py COBOL store rules: truncation, ROUNDED modes, SIZE ERROR
src/cobview/runtime.py    libcob runtime, compile(), Program, external()
src/cobview/source.py     program signatures from PROCEDURE DIVISION USING + LINKAGE
cobol/                    sample copybooks and COBOL programs used by tests and demos
```
