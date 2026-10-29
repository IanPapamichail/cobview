"""Parse COBOL copybooks into byte-exact record layouts.

The parser understands the subset of COBOL data description entries that
describe stored data: levels 01-49 / 77 / 88, PIC, USAGE, OCCURS (fixed),
REDEFINES and SIGN.  It computes the offset and size of every item so
that a buffer can be interpreted without copying it.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterator

__all__ = ["CopybookError", "Field", "Layout", "Options"]


class CopybookError(ValueError):
    """Raised when a copybook cannot be parsed or uses unsupported syntax."""


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

_BINARY_SIZE_TABLES = {
    # max digits -> bytes
    "1-2-4-8": ((2, 1), (4, 2), (9, 4), (18, 8)),  # GnuCOBOL default
    "2-4-8": ((4, 2), (9, 4), (18, 8)),  # IBM Enterprise COBOL
}


@dataclass(frozen=True)
class Options:
    """How the compiler that produced the data laid out its storage.

    The defaults match GnuCOBOL's ``default.conf`` on the current machine.
    For IBM mainframe data use ``Options.ibm()``.
    """

    encoding: str = "ascii"
    binary_sizes: str = "1-2-4-8"
    comp_byteorder: str = "big"  # COMP / COMP-4 / BINARY
    native_byteorder: str = sys.byteorder  # COMP-5, BINARY-LONG, COMP-1/2

    def __post_init__(self) -> None:
        if self.binary_sizes not in _BINARY_SIZE_TABLES:
            raise ValueError(
                f"binary_sizes must be one of {sorted(_BINARY_SIZE_TABLES)}"
            )
        for bo in (self.comp_byteorder, self.native_byteorder):
            if bo not in ("big", "little"):
                raise ValueError("byte order must be 'big' or 'little'")
        "x".encode(self.encoding)  # fail early on unknown codecs

    @classmethod
    def ibm(cls, encoding: str = "cp037") -> "Options":
        """IBM Enterprise COBOL on z/OS: EBCDIC, big-endian, 2-4-8 binaries."""
        return cls(
            encoding=encoding,
            binary_sizes="2-4-8",
            comp_byteorder="big",
            native_byteorder="big",
        )

    @property
    def ebcdic(self) -> bool:
        return "0".encode(self.encoding) == b"\xf0"

    def binary_size(self, digits: int) -> int:
        for max_digits, size in _BINARY_SIZE_TABLES[self.binary_sizes]:
            if digits <= max_digits:
                return size
        raise CopybookError(f"binary item with {digits} digits is not supported")


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------

#: kinds of storage an elementary item can have
KINDS = ("group", "alnum", "edited", "zoned", "packed", "binary", "float")


@dataclass(eq=False)
class Field:
    """One data item of a copybook, with its position in the record.

    ``offset`` is relative to the start of the record and refers to the
    first occurrence of every enclosing OCCURS.  ``size`` is the size of a
    single occurrence; ``dims`` lists ``(count, stride)`` for every OCCURS
    from the outermost one down to this item.
    """

    name: str
    level: int
    kind: str = "group"
    usage: str = "DISPLAY"
    pic: str | None = None
    digits: int = 0
    scale: int = 0
    signed: bool = False
    sign_leading: bool = False
    sign_separate: bool = False
    byteorder: str = "big"
    occurs: int | None = None
    redefines: str | None = None
    offset: int = 0
    size: int = 0
    dims: tuple[tuple[int, int], ...] = ()
    parent: "Field | None" = field(default=None, repr=False)
    children: list["Field"] = field(default_factory=list, repr=False)
    conditions: dict[str, list] = field(default_factory=dict, repr=False)
    external: bool = False
    line: int = 0

    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    @property
    def is_filler(self) -> bool:
        return self.name == "FILLER"

    @property
    def total_size(self) -> int:
        return self.size * (self.occurs or 1)

    @property
    def path(self) -> str:
        parts = []
        node: Field | None = self
        while node is not None and node.level > 0:
            parts.append(node.name)
            node = node.parent
        return ".".join(reversed(parts))

    def walk(self) -> Iterator["Field"]:
        """This item and all its descendants, in declaration order."""
        yield self
        for child in self.children:
            yield from child.walk()

    def type_label(self) -> str:
        if self.kind == "group":
            return "group"
        if self.kind in ("binary", "float") and not self.pic:
            return self.usage
        label = self.pic or ""
        if self.usage != "DISPLAY":
            label += f" {self.usage}"
        if self.sign_separate:
            label += " SIGN " + ("LEADING" if self.sign_leading else "TRAILING")
            label += " SEPARATE"
        elif self.sign_leading:
            label += " SIGN LEADING"
        return label.strip()


# ---------------------------------------------------------------------------
# Source handling: fixed / free format, comments, statements
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[^\s\"']+")


def _detect_fixed(lines: list[str]) -> bool:
    for line in lines:
        if not line.strip():
            continue
        head = line[:6]
        if any(c not in " 0123456789" for c in head):
            return False
        if len(line) > 6 and line[6] not in " *-/Dd":
            return False
    return True


def _strip_inline_comment(text: str) -> str:
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "*" and text[i + 1 : i + 2] == ">":
            return text[:i]
    return text


def _source_lines(text: str, fmt: str) -> Iterator[tuple[int, str]]:
    lines = text.expandtabs(8).splitlines()
    fixed = _detect_fixed(lines) if fmt == "auto" else fmt == "fixed"
    for number, line in enumerate(lines, start=1):
        if fixed:
            indicator = line[6:7]
            if indicator in ("*", "/", "D", "d"):
                continue  # comment, page eject or debugging line
            if indicator == "-":
                raise CopybookError(
                    f"line {number}: continuation lines are not supported yet"
                )
            body = line[7:72]
        else:
            body = line
            if body.lstrip().startswith("*>"):
                continue
        body = _strip_inline_comment(body)
        if body.strip():
            yield number, body


def _statements(text: str, fmt: str) -> Iterator[tuple[int, list[str]]]:
    tokens: list[str] = []
    start = 0
    for number, body in _source_lines(text, fmt):
        for match in _TOKEN_RE.finditer(body):
            tok = match.group(0)
            if not tokens:
                start = number
            if tok[0] in "\"'":
                tokens.append(tok)
                continue
            if tok == ".":
                if tokens:
                    yield start, tokens
                tokens = []
                continue
            ends = tok.endswith(".")
            tok = tok.rstrip(".") if ends else tok
            tok = tok.rstrip(",;")
            if tok:
                tokens.append(tok)
            if ends:
                yield start, tokens
                tokens = []
    if tokens:
        raise CopybookError(f"line {start}: entry is missing its final period")


# ---------------------------------------------------------------------------
# Clause parsing
# ---------------------------------------------------------------------------

_USAGES = {
    "DISPLAY": "DISPLAY",
    "COMP": "COMP",
    "COMPUTATIONAL": "COMP",
    "COMP-4": "COMP",
    "COMPUTATIONAL-4": "COMP",
    "BINARY": "COMP",
    "COMP-5": "COMP-5",
    "COMPUTATIONAL-5": "COMP-5",
    "COMP-X": "COMP-X",
    "COMPUTATIONAL-X": "COMP-X",
    "COMP-3": "COMP-3",
    "COMPUTATIONAL-3": "COMP-3",
    "PACKED-DECIMAL": "COMP-3",
    "COMP-1": "COMP-1",
    "COMPUTATIONAL-1": "COMP-1",
    "FLOAT-SHORT": "COMP-1",
    "COMP-2": "COMP-2",
    "COMPUTATIONAL-2": "COMP-2",
    "FLOAT-LONG": "COMP-2",
    "BINARY-CHAR": "BINARY-CHAR",
    "BINARY-SHORT": "BINARY-SHORT",
    "BINARY-LONG": "BINARY-LONG",
    "BINARY-DOUBLE": "BINARY-DOUBLE",
    "POINTER": "POINTER",
    "INDEX": "INDEX",
}
_FIXED_BINARIES = {
    "BINARY-CHAR": 1,
    "BINARY-SHORT": 2,
    "BINARY-LONG": 4,
    "BINARY-DOUBLE": 8,
    "POINTER": 8,
    "INDEX": 4,
}
_UNSUPPORTED_USAGES = {"NATIONAL", "COMP-6", "COMPUTATIONAL-6", "FLOAT-EXTENDED"}

_CLAUSE_WORDS = {
    "PIC", "PICTURE", "USAGE", "OCCURS", "REDEFINES", "SIGN", "LEADING",
    "TRAILING", "VALUE", "VALUES", "SYNC", "SYNCHRONIZED", "JUST",
    "JUSTIFIED", "BLANK", "GLOBAL", "EXTERNAL", "INDEXED", "ASCENDING",
    "DESCENDING", "RENAMES", "SIGNED", "UNSIGNED",
} | set(_USAGES) | _UNSUPPORTED_USAGES

_FIGURATIVE = {
    "ZERO": 0, "ZEROS": 0, "ZEROES": 0,
    "SPACE": " ", "SPACES": " ",
    "LOW-VALUE": "\x00", "LOW-VALUES": "\x00",
    "HIGH-VALUE": "\xff", "HIGH-VALUES": "\xff",
}


def _literal(tok: str):
    if tok[0] in "\"'":
        q = tok[0]
        return tok[1:-1].replace(q + q, q)
    up = tok.upper()
    if up in _FIGURATIVE:
        return _FIGURATIVE[up]
    try:
        d = Decimal(tok)
    except ArithmeticError:
        raise CopybookError(f"cannot read literal {tok!r}") from None
    return int(d) if d == d.to_integral_value() and "." not in tok else d


@dataclass
class _Pic:
    kind: str  # alnum | edited | numeric
    digits: int = 0
    scale: int = 0
    signed: bool = False
    length: int = 0


def _parse_pic(pic: str, line: int) -> _Pic:
    up = pic.upper()
    try:
        expanded = re.sub(
            r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), up
        )
    except ValueError:
        raise CopybookError(f"line {line}: bad PIC {pic!r}") from None
    if "(" in expanded or ")" in expanded:
        raise CopybookError(f"line {line}: bad PIC {pic!r}")
    if "N" in expanded:
        raise CopybookError(f"line {line}: national items (PIC N) are not supported yet")
    if "X" in expanded or "A" in expanded:
        return _Pic("alnum", length=len(expanded))
    if set(expanded) <= set("9SVP"):
        if "P" in expanded:
            raise CopybookError(f"line {line}: PIC P scaling is not supported yet")
        if expanded.count("S") > 1 or expanded.count("V") > 1:
            raise CopybookError(f"line {line}: bad PIC {pic!r}")
        if "S" in expanded and not expanded.startswith("S"):
            raise CopybookError(f"line {line}: S must come first in PIC {pic!r}")
        digits = expanded.count("9")
        scale = len(expanded.split("V", 1)[1]) if "V" in expanded else 0
        if digits == 0:
            raise CopybookError(f"line {line}: numeric PIC {pic!r} has no digits")
        return _Pic("numeric", digits=digits, scale=scale, signed="S" in expanded)
    # numeric-edited: stored as characters, V takes no space
    return _Pic("edited", length=len(expanded.replace("V", "")))


def _parse_entry(line: int, tokens: list[str], options: Options) -> tuple[Field, dict]:
    try:
        level = int(tokens[0])
    except ValueError:
        raise CopybookError(f"line {line}: expected a level number, got {tokens[0]!r}") from None
    if level == 66:
        raise CopybookError(f"line {line}: level 66 RENAMES is not supported yet")
    if not (1 <= level <= 49 or level in (77, 88)):
        raise CopybookError(f"line {line}: invalid level number {level}")

    i = 1
    name = "FILLER"
    if i < len(tokens) and tokens[i].upper() not in _CLAUSE_WORDS:
        name = tokens[i].upper()
        i += 1

    f = Field(name=name, level=level, line=line)
    info: dict = {"usage_explicit": False, "values": []}

    def take(words=()) -> str | None:
        nonlocal i
        while i < len(tokens) and tokens[i].upper() in words:
            i += 1
        if i >= len(tokens):
            return None
        tok = tokens[i]
        i += 1
        return tok

    while i < len(tokens):
        tok = tokens[i]
        up = tok.upper()
        i += 1
        if up in ("PIC", "PICTURE"):
            pic = take(("IS",))
            if pic is None:
                raise CopybookError(f"line {line}: PIC without a picture string")
            f.pic = pic.upper()
        elif up == "USAGE":
            word = take(("IS",))
            if word is None:
                raise CopybookError(f"line {line}: USAGE without a usage")
            i -= 1  # re-read the usage word in the next iteration
        elif up in _USAGES:
            f.usage = _USAGES[up]
            info["usage_explicit"] = True
        elif up in _UNSUPPORTED_USAGES:
            raise CopybookError(f"line {line}: USAGE {up} is not supported yet")
        elif up == "SIGNED":
            info["signed_word"] = True
        elif up == "UNSIGNED":
            info["signed_word"] = False
        elif up == "OCCURS":
            count = take()
            if count is None or not count.isdigit():
                raise CopybookError(f"line {line}: OCCURS needs a number")
            nxt = tokens[i].upper() if i < len(tokens) else ""
            if nxt == "TO":
                raise CopybookError(
                    f"line {line}: OCCURS ... DEPENDING ON is not supported yet"
                )
            f.occurs = int(count)
            if f.occurs < 1:
                raise CopybookError(f"line {line}: OCCURS must be at least 1")
            # skip TIMES, ASCENDING KEY IS names..., INDEXED BY names...
            while i < len(tokens):
                w = tokens[i].upper()
                if w == "DEPENDING":
                    raise CopybookError(
                        f"line {line}: OCCURS ... DEPENDING ON is not supported yet"
                    )
                if w == "TIMES":
                    i += 1
                elif w in ("ASCENDING", "DESCENDING", "INDEXED"):
                    i += 1
                    while i < len(tokens) and tokens[i].upper() in ("KEY", "IS", "BY"):
                        i += 1
                    while i < len(tokens) and tokens[i].upper() not in _CLAUSE_WORDS:
                        i += 1  # key or index names
                else:
                    break
        elif up == "REDEFINES":
            target = take()
            if target is None:
                raise CopybookError(f"line {line}: REDEFINES needs a name")
            f.redefines = target.upper()
        elif up in ("SIGN", "LEADING", "TRAILING"):
            if up == "SIGN":
                pos = take(("IS",))
                up = (pos or "").upper()
            if up not in ("LEADING", "TRAILING"):
                raise CopybookError(f"line {line}: SIGN needs LEADING or TRAILING")
            f.sign_leading = up == "LEADING"
            if i < len(tokens) and tokens[i].upper() == "SEPARATE":
                f.sign_separate = True
                i += 1
                if i < len(tokens) and tokens[i].upper() == "CHARACTER":
                    i += 1
        elif up in ("VALUE", "VALUES"):
            while i < len(tokens) and tokens[i].upper() in ("IS", "ARE"):
                i += 1
            values: list = []
            while i < len(tokens) and tokens[i].upper() not in _CLAUSE_WORDS - {
                "ZERO", "SPACE"
            }:
                w = tokens[i].upper()
                if w in ("THRU", "THROUGH") and values:
                    i += 1
                    hi = _literal(tokens[i])
                    values[-1] = (values[-1], hi)
                elif w == "ALL":
                    pass
                else:
                    values.append(_literal(tokens[i]))
                i += 1
            info["values"] = values
        elif up in ("SYNC", "SYNCHRONIZED"):
            raise CopybookError(f"line {line}: SYNCHRONIZED alignment is not supported yet")
        elif up == "EXTERNAL":
            f.external = True
            if i < len(tokens) and tokens[i].upper() == "AS":
                raise CopybookError(f"line {line}: EXTERNAL AS is not supported yet")
        elif up in ("JUST", "JUSTIFIED", "GLOBAL"):
            if i < len(tokens) and tokens[i].upper() == "RIGHT":
                i += 1
        elif up == "BLANK":
            take(("WHEN",))  # ZERO
        else:
            raise CopybookError(f"line {line}: unexpected word {tok!r}")
    return f, info


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    return name.upper().replace("_", "-")


class Layout:
    """The byte layout of one record described by a copybook."""

    def __init__(self, root: Field, options: Options | None = None):
        self.root = root
        self.options = options or Options()
        self._index: dict[str, list[Field]] = {}
        self._conditions: dict[str, list[tuple[Field, list]]] = {}
        self._resolve_cache: dict = {}
        for f in root.walk():
            if f.level > 0 and not f.is_filler:
                self._index.setdefault(f.name, []).append(f)
            for cname, values in f.conditions.items():
                self._conditions.setdefault(cname, []).append((f, values))

    # -- construction -------------------------------------------------------

    @classmethod
    def from_copybook(
        cls,
        source: str | Path,
        *,
        record: str | None = None,
        format: str = "auto",
        options: Options | None = None,
        **option_kwargs,
    ) -> "Layout":
        """Build a layout from a copybook path or copybook text.

        ``record`` picks a 01-level record when the copybook holds several.
        Extra keyword arguments (``encoding``, ``binary_sizes``, ...) build
        an :class:`Options`.
        """
        if options is None:
            options = Options(**option_kwargs)
        elif option_kwargs:
            raise TypeError("pass either options= or option keywords, not both")
        if format not in ("auto", "fixed", "free"):
            raise ValueError("format must be 'auto', 'fixed' or 'free'")
        text = _read_source(source)
        roots = _build_tree(text, format, options)
        if record is None:
            if len(roots) > 1:
                names = ", ".join(r.name for r in roots)
                raise CopybookError(
                    f"copybook holds several records ({names}); pass record="
                )
            root = roots[0]
        else:
            matches = [r for r in roots if r.name == _norm(record)]
            if not matches:
                raise CopybookError(f"no record named {record!r}")
            root = matches[0]
        _assign_offsets(root, 0)
        _assign_dims(root)
        return cls(root, options)

    @classmethod
    def records(
        cls,
        source: str | Path,
        *,
        format: str = "auto",
        options: Options | None = None,
        lenient: bool = False,
        **option_kwargs,
    ):
        """Every 01/77 record in ``source`` as ``{name: Layout}``.

        With ``lenient=True`` a record that cannot be parsed is skipped and
        the result is ``(layouts, errors)`` where ``errors`` maps record
        names to the :class:`CopybookError` explaining why.
        """
        if options is None:
            options = Options(**option_kwargs)
        text = _read_source(source)
        groups: list[list] = []
        for stmt in _statements(text, format):
            level = stmt[1][0]
            if level in ("01", "1", "77") or not groups:
                groups.append([])
            groups[-1].append(stmt)
        layouts: dict[str, Layout] = {}
        errors: dict[str, CopybookError] = {}
        for group in groups:
            tokens = group[0][1]
            name = tokens[1].upper() if len(tokens) > 1 else f"line {group[0][0]}"
            try:
                for root in _tree_from_statements(group, options):
                    _assign_offsets(root, 0)
                    _assign_dims(root)
                    layouts[root.name] = cls(root, options)
            except CopybookError as exc:
                if not lenient:
                    raise
                errors[name] = exc
        return (layouts, errors) if lenient else layouts

    # -- inspection ---------------------------------------------------------

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def size(self) -> int:
        return self.root.size

    def fields(self) -> list[Field]:
        """Every named item, in declaration order."""
        return [f for f in self.root.walk() if f.level > 0]

    def elementary(self) -> list[Field]:
        return [f for f in self.root.walk() if not f.is_group and not f.is_filler]

    def find(self, name: str, within: Field | None = None) -> Field:
        """Look up an item by name, ``A.B`` path, or ``B OF A`` qualification."""
        candidates = self.find_all(name, within)
        if not candidates:
            raise KeyError(name)
        if len(candidates) > 1:
            paths = ", ".join(c.path for c in candidates)
            raise KeyError(f"{name!r} is ambiguous ({paths}); qualify it")
        return candidates[0]

    def find_all(self, name: str, within: Field | None = None) -> list[Field]:
        parts = _qualifiers(name)
        target, quals = parts[-1], parts[:-1]
        found = []
        for f in self._index.get(target, []):
            if within is not None and not _is_descendant(f, within):
                continue
            node, ok = f.parent, True
            for q in reversed(quals):
                while node is not None and node.name != q:
                    node = node.parent
                if node is None:
                    ok = False
                    break
                node = node.parent
            if ok:
                found.append(f)
        return found

    def resolve(self, name: str, within: Field):
        """Cached lookup used by record views.

        Returns ``("field", Field)`` or ``("condition", (Field, values))``.
        Raises ``KeyError`` when the name is unknown or ambiguous.
        """
        key = (id(within), name)
        hit = self._resolve_cache.get(key)
        if hit is None:
            try:
                hit = ("field", self.find(name, within))
            except KeyError as exc:
                if self.find_all(name, within):
                    raise  # ambiguous
                cond = self.condition(name, within)
                if cond is None:
                    raise KeyError(name) from exc
                hit = ("condition", cond)
            self._resolve_cache[key] = hit
        return hit

    def condition(self, name: str, within: Field | None = None):
        """Return ``(field, values)`` for an 88-level condition name, or None."""
        hits = [
            (f, v)
            for f, v in self._conditions.get(_norm(name), [])
            if within is None or _is_descendant(f, within)
        ]
        if len(hits) > 1:
            raise KeyError(f"condition {name!r} is ambiguous")
        return hits[0] if hits else None

    def describe(self) -> str:
        """A table of every item with its offset, length and storage type."""
        rows = [("LVL", "NAME", "OFFSET", "LEN", "TYPE", "OCCURS")]
        for f in self.root.walk():
            if f.level == 0:
                continue
            depth = 0
            node = f.parent
            while node is not None and node.level > 0:
                depth += 1
                node = node.parent
            name = "  " * depth + f.name
            if f.redefines:
                name += f" (REDEFINES {f.redefines})"
            rows.append(
                (
                    f"{f.level:02d}",
                    name,
                    str(f.offset),
                    str(f.size),
                    f.type_label(),
                    str(f.occurs) if f.occurs else "",
                )
            )
            for cname, values in f.conditions.items():
                vals = ", ".join(_fmt_value(v) for v in values)
                rows.append(("88", "  " * (depth + 1) + cname, "", "", f"= {vals}", ""))
        widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
        out = []
        for r in rows:
            cells = [
                r[0].ljust(widths[0]),
                r[1].ljust(widths[1]),
                r[2].rjust(widths[2]),
                r[3].rjust(widths[3]),
                r[4].ljust(widths[4]),
                r[5],
            ]
            out.append("  ".join(cells).rstrip())
        out.append(f"record size: {self.size} bytes")
        return "\n".join(out)

    def __repr__(self) -> str:
        return f"<Layout {self.name} {self.size} bytes, {len(self.elementary())} fields>"


def _fmt_value(v) -> str:
    if isinstance(v, tuple):
        return f"{_fmt_value(v[0])} THRU {_fmt_value(v[1])}"
    return repr(v)


def _qualifiers(name: str) -> list[str]:
    name = name.strip()
    if re.search(r"\s+(OF|IN)\s+", name, re.I):
        parts = re.split(r"\s+(?:OF|IN)\s+", name, flags=re.I)
        return [_norm(p) for p in reversed(parts)]
    return [_norm(p) for p in name.split(".")]


def _is_descendant(f: Field, ancestor: Field) -> bool:
    node: Field | None = f
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _read_source(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8", errors="replace")
    if "\n" not in source and len(source) < 4096:
        p = Path(source)
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
        if "/" in source or "\\" in source or p.suffix.lower() in (
            ".cpy", ".cbl", ".cob", ".copy"
        ):
            raise FileNotFoundError(source)
    return source


def _build_tree(text: str, fmt: str, options: Options) -> list[Field]:
    return _tree_from_statements(_statements(text, fmt), options)


def _tree_from_statements(statements, options: Options) -> list[Field]:
    synthetic = Field(name="RECORD", level=0)
    roots: list[Field] = []
    entries: list[tuple[Field, dict]] = []
    stack: list[tuple[Field, dict]] = []
    last_item: tuple[Field, dict] | None = None

    for line, tokens in statements:
        f, info = _parse_entry(line, tokens, options)
        if f.level == 88:
            if last_item is None:
                raise CopybookError(f"line {line}: level 88 without an item above it")
            owner = last_item[0]
            if not info["values"]:
                raise CopybookError(f"line {line}: level 88 {f.name} needs VALUE")
            owner.conditions[f.name] = info["values"]
            continue

        if f.level in (1, 77):
            stack.clear()
        while stack and stack[-1][0].level >= f.level:
            stack.pop()
        if stack:
            parent, pinfo = stack[-1]
            if parent.level == 77:
                raise CopybookError(f"line {line}: level 77 items cannot have subordinates")
            f.parent = parent
            parent.children.append(f)
            if not info["usage_explicit"] and pinfo["usage_explicit"]:
                # a group's USAGE applies to every item under it
                f.usage = parent.usage
                info["usage_explicit"] = True
        elif f.level in (1, 77):
            roots.append(f)
        else:
            # a fragment copybook without an 01 level
            if synthetic not in roots:
                roots.append(synthetic)
            f.parent = synthetic
            synthetic.children.append(f)

        entries.append((f, info))
        stack.append((f, info))
        last_item = (f, info)

    if not roots:
        raise CopybookError("no data items found")
    for f, info in entries:
        if f.children:
            if f.pic:
                raise CopybookError(
                    f"line {f.line}: {f.name} has a PIC but also subordinate items"
                )
            f.kind = "group"
        else:
            _classify(f, info, options)
    return roots


def _classify(f: Field, info: dict, options: Options) -> None:
    """Decide the storage kind of an elementary item from its PIC and USAGE."""
    usage = f.usage
    f.byteorder = options.comp_byteorder
    if usage in ("COMP-1", "COMP-2"):
        if f.pic:
            raise CopybookError(f"line {f.line}: {usage} items take no PIC")
        f.kind, f.size, f.signed = "float", (4 if usage == "COMP-1" else 8), True
        f.byteorder = options.native_byteorder
        return
    if usage in _FIXED_BINARIES:
        if f.pic:
            raise CopybookError(f"line {f.line}: {usage} items take no PIC")
        f.kind, f.size = "binary", _FIXED_BINARIES[usage]
        f.signed = info.get("signed_word", usage not in ("POINTER",))
        f.byteorder = options.native_byteorder
        return
    if f.pic is None:
        raise CopybookError(
            f"line {f.line}: {f.name} has no PIC and no subordinate items"
        )

    pic = _parse_pic(f.pic, f.line)
    if pic.kind in ("alnum", "edited"):
        if usage != "DISPLAY":
            raise CopybookError(f"line {f.line}: PIC {f.pic} cannot be USAGE {usage}")
        f.kind, f.size = pic.kind, pic.length
        return

    f.digits, f.scale, f.signed = pic.digits, pic.scale, pic.signed
    if (f.sign_leading or f.sign_separate) and not f.signed:
        raise CopybookError(f"line {f.line}: SIGN clause on an unsigned item")
    if usage == "DISPLAY":
        f.kind = "zoned"
        f.size = pic.digits + (1 if f.sign_separate else 0)
    elif usage == "COMP-3":
        f.kind = "packed"
        f.size = pic.digits // 2 + 1
    elif usage in ("COMP", "COMP-5", "COMP-X"):
        f.kind = "binary"
        f.size = options.binary_size(pic.digits)
        if usage == "COMP-5":
            f.byteorder = options.native_byteorder
        elif usage == "COMP-X":
            f.byteorder = "big"
    else:
        raise CopybookError(f"line {f.line}: USAGE {usage} with PIC {f.pic}")
    if f.sign_separate and f.kind != "zoned":
        raise CopybookError(f"line {f.line}: SIGN SEPARATE needs USAGE DISPLAY")


def _assign_offsets(f: Field, offset: int) -> int:
    """Place ``f`` at ``offset``; return the offset just past all its occurrences."""
    f.offset = offset
    if f.children:
        cursor = offset
        end = offset
        placed: dict[str, Field] = {}
        for c in f.children:
            if c.redefines:
                target = placed.get(c.redefines)
                if target is None:
                    raise CopybookError(
                        f"line {c.line}: {c.name} REDEFINES {c.redefines}, "
                        "which is not an earlier item at the same level"
                    )
                c_end = _assign_offsets(c, target.offset)
            else:
                c_end = _assign_offsets(c, cursor)
                cursor = c_end
            end = max(end, c_end)
            if not c.is_filler:
                placed[c.name] = c
        f.size = end - offset
    return offset + f.total_size


def _assign_dims(f: Field, outer: tuple = ()) -> None:
    """Record ``(count, stride)`` for every OCCURS from the outermost down."""
    f.dims = outer + (((f.occurs, f.size),) if f.occurs else ())
    for c in f.children:
        _assign_dims(c, f.dims)
