"""Zero-copy record views over any buffer: bytes, bytearray, mmap, ctypes memory.

A :class:`Record` never copies its bytes.  Reading an attribute decodes
just that field; assigning to one encodes the value straight into the
underlying memory, so the change is visible to COBOL (or the file) at once.
"""

from __future__ import annotations

import builtins
import mmap
import os
from collections.abc import Sequence
from pathlib import Path

from .arithmetic import ARITHMETIC
from .codecs import CobolDataError, decode, encode
from .copybook import Field, Layout

__all__ = ["Record", "OccursView", "Records", "RecordFile", "open", "records", "view"]


def _as_bytes_view(buffer) -> memoryview:
    mv = buffer if isinstance(buffer, memoryview) else memoryview(buffer)
    if mv.format != "B" or mv.ndim != 1:
        mv = mv.cast("B")
    return mv


def _check_arithmetic(arithmetic: str) -> str:
    if arithmetic not in ARITHMETIC:
        raise ValueError(f"arithmetic must be one of {ARITHMETIC}, not {arithmetic!r}")
    return arithmetic


def _read_only_error() -> TypeError:
    return TypeError(
        "this view is read-only; open the file with mode='r+' or pass a writable buffer"
    )


class _Node:
    """Shared plumbing for Record and OccursView."""

    __slots__ = ("_mv", "_layout", "_delta", "_arith")

    def _value(self, f: Field, delta: int, resolved: int):
        remaining = f.dims[resolved:]
        if remaining:
            return OccursView(self._mv, self._layout, f, delta, remaining, self._arith)
        if f.is_group:
            return Record(self._mv, self._layout, f, delta, self._arith)
        start = f.offset + delta
        try:
            return decode(f, self._mv[start : start + f.size], self._layout.options)
        except CobolDataError as exc:
            raise type(exc)(f"{f.path}: {exc}") from None

    def _store(self, f: Field, delta: int, resolved: int, value) -> None:
        remaining = f.dims[resolved:]
        if remaining:
            target = OccursView(self._mv, self._layout, f, delta, remaining, self._arith)
            if len(value) != len(target):
                raise ValueError(
                    f"{f.name} has {len(target)} occurrences, got {len(value)} values"
                )
            for i, v in enumerate(value):
                target[i] = v
            return
        start = f.offset + delta
        if f.is_group:
            data = bytes(value) if not isinstance(value, str) else value.encode(
                self._layout.options.encoding
            )
            if len(data) != f.size:
                raise CobolDataError(
                    f"group {f.name} is {f.size} bytes; got {len(data)} bytes"
                )
        else:
            try:
                data = encode(f, value, self._layout.options, self._arith)
            except CobolDataError as exc:
                raise type(exc)(f"{f.path}: {exc}") from None
        if self._mv.readonly:
            raise _read_only_error()
        self._mv[start : start + f.size] = data


class Record(_Node):
    """A typed, zero-copy view of one record (or one group inside it).

    Fields are attributes: ``rec.CUST_BALANCE`` or ``rec.cust_balance`` or
    ``rec["CUST-BALANCE"]``.  88-level condition names read as booleans and
    can be set to ``True``.
    """

    __slots__ = ("_field",)

    def __init__(self, mv: memoryview, layout: Layout, field: Field, delta: int = 0,
                 arithmetic: str = "strict"):
        object.__setattr__(self, "_mv", mv)
        object.__setattr__(self, "_layout", layout)
        object.__setattr__(self, "_field", field)
        object.__setattr__(self, "_delta", delta)
        object.__setattr__(self, "_arith", arithmetic)

    # -- field access -------------------------------------------------------

    def _lookup(self, name: str):
        try:
            return self._layout.resolve(name, self._field)
        except KeyError as exc:
            msg = exc.args[0] if exc.args else name
            raise AttributeError(
                f"{self._field.name} has no field {msg!r}"
                if msg == name
                else str(msg)
            ) from None

    def _condition_value(self, owner: Field, values: list) -> bool:
        current = self._value(owner, self._delta, len(self._field.dims))
        for v in values:
            if isinstance(v, tuple):
                if v[0] <= current <= v[1]:
                    return True
            elif current == v or (isinstance(v, str) and str(current) == v.rstrip()):
                return True
        return False

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        kind, target = self._lookup(name)
        if kind == "condition":
            owner, values = target
            return self._condition_value(owner, values)
        if target is self._field:
            return self
        return self._value(target, self._delta, len(self._field.dims))

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_"):
            raise AttributeError(f"cannot set {name}")
        kind, target = self._lookup(name)
        if kind == "condition":
            owner, values = target
            if value is not True:
                raise ValueError(f"{name} can only be set to True")
            first = values[0][0] if isinstance(values[0], tuple) else values[0]
            self._store(owner, self._delta, len(self._field.dims), first)
            return
        self._store(target, self._delta, len(self._field.dims), value)

    __getitem__ = __getattr__

    def __setitem__(self, name: str, value) -> None:
        self.__setattr__(name, value)

    def __dir__(self):
        names = []
        for f in self._field.walk():
            if f is not self._field and not f.is_filler:
                names.append(f.name.replace("-", "_"))
                names.extend(c.replace("-", "_") for c in f.conditions)
        return sorted(set(names)) + ["arithmetic", "field", "layout", "raw", "to_dict"]

    # -- whole-record helpers -------------------------------------------------

    @property
    def field(self) -> Field:
        return self._field

    @property
    def layout(self) -> Layout:
        return self._layout

    @property
    def arithmetic(self) -> str:
        """``"strict"`` or ``"cobol"``: the rules assignments follow."""
        return self._arith

    @property
    def raw(self) -> memoryview:
        """The bytes of this record or group, as a zero-copy memoryview."""
        start = self._field.offset + self._delta
        return self._mv[start : start + self._field.size]

    def to_dict(self, *, redefines: bool = False) -> dict:
        """Decode every field into a plain dict (groups nest, OCCURS become lists).

        REDEFINES items are skipped unless ``redefines=True``, because an
        alternative view of the same bytes often holds invalid data.
        """
        out = {}
        for child in self._field.children:
            if child.is_filler or (child.redefines and not redefines):
                continue
            value = self._value(child, self._delta, len(self._field.dims))
            out[child.name] = _plain(value, redefines)
        return out

    def __repr__(self) -> str:
        parts = []
        for f in self._field.walk():
            if f is self._field or f.is_group or f.is_filler or f.redefines:
                continue
            if len(f.dims) > len(self._field.dims):
                continue
            try:
                val = repr(self._value(f, self._delta, len(self._field.dims)))
            except CobolDataError:
                val = "<invalid>"
            parts.append(f"{f.name}={val}")
            if len(parts) == 6:
                parts.append("...")
                break
        return f"{self._field.name}({', '.join(parts)})"


class OccursView(_Node, Sequence):
    """The occurrences of an OCCURS item, indexed from 0 like any Python list."""

    __slots__ = ("_field", "_dims")

    def __init__(self, mv, layout, field: Field, delta: int, dims: tuple,
                 arithmetic: str = "strict"):
        self._mv = mv
        self._layout = layout
        self._field = field
        self._delta = delta
        self._dims = dims
        self._arith = arithmetic

    def __len__(self) -> int:
        return self._dims[0][0]

    def _index(self, i: int) -> int:
        n = len(self)
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError(f"{self._field.name} index {i} out of range (0..{n - 1})")
        return i

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        i = self._index(i)
        delta = self._delta + i * self._dims[0][1]
        resolved = len(self._field.dims) - len(self._dims) + 1
        return self._value(self._field, delta, resolved)

    def __setitem__(self, i: int, value) -> None:
        i = self._index(i)
        delta = self._delta + i * self._dims[0][1]
        resolved = len(self._field.dims) - len(self._dims) + 1
        self._store(self._field, delta, resolved, value)

    def to_list(self) -> list:
        return [_plain(v, False) for v in self]

    def __repr__(self) -> str:
        return repr(list(self))


def _plain(value, redefines: bool):
    if isinstance(value, Record):
        return value.to_dict(redefines=redefines)
    if isinstance(value, OccursView):
        return [_plain(v, redefines) for v in value]
    return value


class Records(Sequence):
    """A sequence of fixed-length records over one buffer, without copying."""

    def __init__(self, buffer, layout: Layout, *, arithmetic: str = "strict"):
        self._arith = _check_arithmetic(arithmetic)
        mv = _as_bytes_view(buffer)
        size = layout.size
        if size <= 0:
            raise ValueError("layout has no size")
        n, extra = divmod(len(mv), size)
        if extra:
            raise CobolDataError(
                f"{len(mv)} bytes is not a whole number of {size}-byte "
                f"{layout.name} records ({extra} bytes left over)"
            )
        self._mv = mv
        self._layout = layout
        self._n = n

    @property
    def layout(self) -> Layout:
        return self._layout

    @property
    def buffer(self) -> memoryview:
        return self._mv

    @property
    def readonly(self) -> bool:
        return self._mv.readonly

    def __len__(self) -> int:
        return self._n

    def __getitem__(self, i):
        size = self._layout.size
        if isinstance(i, slice):
            start, stop, step = i.indices(self._n)
            if step != 1:
                return [self[j] for j in range(start, stop, step)]
            return Records(self._mv[start * size : max(start, stop) * size], self._layout,
                           arithmetic=self._arith)
        if i < 0:
            i += self._n
        if not 0 <= i < self._n:
            raise IndexError(f"record {i} out of range (0..{self._n - 1})")
        return Record(self._mv[i * size : (i + 1) * size], self._layout, self._layout.root,
                      0, self._arith)

    def __iter__(self):
        for i in range(self._n):
            yield self[i]

    # NumPy access lives in columns.py so the core works without NumPy.
    def column(self, name: str, *, exact: bool = False):
        """One field across all records as a NumPy array.

        Binary and floating-point fields come back as zero-copy views (writes
        go straight to the buffer).  Packed and zoned decimals are decoded
        with vectorized NumPy code: ``float64`` when the PIC has decimal
        places, or exact unscaled ``int64`` with ``exact=True``.  Text comes
        back as a ``str`` array.
        """
        from .columns import column

        return column(self, name, exact=exact)

    def bytes_column(self, name: str):
        """The raw bytes of a field across all records (zero-copy, dtype ``S``)."""
        from .columns import bytes_column

        return bytes_column(self, name)

    def columns(self, names=None, *, exact: bool = False) -> dict:
        """Several columns as a dict, ready for ``pandas.DataFrame(...)``."""
        from .columns import columns

        return columns(self, names, exact=exact)

    def __repr__(self) -> str:
        return f"<Records {self._layout.name} x {self._n}>"


class RecordFile(Records):
    """Records backed by a memory-mapped file.  Use as a context manager."""

    def __init__(self, path, layout: Layout, mode: str = "r", *, arithmetic: str = "strict"):
        if mode not in ("r", "r+"):
            raise ValueError("mode must be 'r' or 'r+'")
        self.path = Path(path)
        self.mode = mode
        with builtins.open(self.path, "rb" if mode == "r" else "r+b") as fh:
            length = os.fstat(fh.fileno()).st_size
            if length == 0:
                self._mmap = None
                buffer = bytearray() if mode == "r+" else b""
            else:
                access = mmap.ACCESS_READ if mode == "r" else mmap.ACCESS_WRITE
                self._mmap = mmap.mmap(fh.fileno(), 0, access=access)
                buffer = self._mmap
        super().__init__(buffer, layout, arithmetic=arithmetic)

    def flush(self) -> None:
        """Write changes made through the views back to disk now."""
        if self._mmap is not None and self.mode == "r+":
            self._mmap.flush()

    def close(self) -> None:
        """Unmap the file.  Views taken from it must not be used afterwards."""
        if self._mmap is None:
            return
        self.flush()
        self._mv.release()
        try:
            self._mmap.close()
        except BufferError:
            # Records or arrays still point into the map; it is unmapped
            # when the last of them is garbage-collected.
            pass
        self._mmap = None

    def __enter__(self) -> "RecordFile":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<RecordFile {self.path.name} {self._layout.name} x {len(self)} mode={self.mode!r}>"


def open(path, layout: Layout, mode: str = "r", *, arithmetic: str = "strict") -> RecordFile:  # noqa: A001
    """Memory-map a file of fixed-length records described by ``layout``."""
    return RecordFile(path, layout, mode, arithmetic=arithmetic)


def records(buffer, layout: Layout, *, arithmetic: str = "strict") -> Records:
    """View any buffer (bytes, bytearray, mmap, ctypes array...) as records."""
    return Records(buffer, layout, arithmetic=arithmetic)


def view(buffer, layout: Layout, offset: int = 0, *, arithmetic: str = "strict") -> Record:
    """A single-record view starting at ``offset`` bytes into ``buffer``.

    ``arithmetic="cobol"`` makes assignments follow COBOL's store rules
    (see :mod:`cobview.arithmetic`); the default ``"strict"`` never loses data.
    """
    mv = _as_bytes_view(buffer)
    end = offset + layout.size
    if offset < 0 or end > len(mv):
        raise CobolDataError(
            f"buffer has {len(mv)} bytes; {layout.name} needs {layout.size} at offset {offset}"
        )
    return Record(mv[offset:end], layout, layout.root, 0, _check_arithmetic(arithmetic))
