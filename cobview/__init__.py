"""cobview: zero-copy, copybook-typed views over COBOL data in Python.

    >>> import cobview
    >>> layout = cobview.Layout.from_copybook("CUSTOMER.cpy")
    >>> with cobview.open("customers.dat", layout) as recs:
    ...     recs[0].CUST_BALANCE
    Decimal('12345.67')
"""

from .arithmetic import on_size_error, rounded
from .errors import CobolDataError, SizeError
from .copybook import CopybookError, Field, Layout, Options
from .runtime import (
    CobolError,
    CobolRuntimeError,
    CobolStopRun,
    CompileError,
    Program,
    Result,
    ReturnCodeError,
    Runtime,
    compile,
    external,
)
from .view import OccursView, Record, RecordFile, Records, open, records, view

__version__ = "0.2.0"

__all__ = [
    "CobolDataError",
    "SizeError",
    "on_size_error",
    "rounded",
    "CobolError",
    "CobolRuntimeError",
    "CobolStopRun",
    "CompileError",
    "Program",
    "Result",
    "ReturnCodeError",
    "Runtime",
    "compile",
    "external",
    "CopybookError",
    "Field",
    "Layout",
    "OccursView",
    "Options",
    "Record",
    "RecordFile",
    "Records",
    "open",
    "records",
    "view",
]
