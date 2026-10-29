"""Read a COBOL program's interface from its source.

COBOL programs declare their interface in a form a machine can read: the
``PROCEDURE DIVISION USING`` header names the parameters, and the LINKAGE
SECTION describes each one byte for byte.  This module turns that into a
:class:`Signature`, so Python can check, allocate and type the arguments
of a program without a separate copybook - and finds the program's
``EXTERNAL`` items too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .copybook import CopybookError, Layout, Options, _source_lines

__all__ = ["Param", "Signature", "SignatureError", "read_signature"]


class SignatureError(CopybookError):
    """The program's interface could not be read from its source."""


@dataclass
class Param:
    name: str
    layout: Layout | None
    by: str = "REFERENCE"  # REFERENCE | CONTENT | VALUE
    optional: bool = False
    error: str | None = None

    def __str__(self) -> str:
        size = f"{self.layout.size} bytes" if self.layout else f"unknown size: {self.error}"
        by = "" if self.by == "REFERENCE" else f"BY {self.by} "
        return f"{by}{self.name} ({size})"


@dataclass
class Signature:
    program_id: str
    params: list[Param] = field(default_factory=list)
    returning: str | None = None
    externals: dict[str, Layout] = field(default_factory=dict)
    linkage: dict[str, Layout] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """True when every parameter has a known layout and is passed by reference."""
        return all(p.layout is not None and p.by != "VALUE" for p in self.params)

    def __str__(self) -> str:
        if not self.params:
            text = f"{self.program_id}: no parameters"
        else:
            text = f"{self.program_id} USING " + ", ".join(str(p) for p in self.params)
        if self.returning:
            text += f" RETURNING {self.returning}"
        return text


_COPY = re.compile(
    r"\bCOPY\s+(?P<name>\"[^\"]+\"|'[^']+'|[\w$#@.-]+)"
    r"(?:\s+(?:OF|IN)\s+(?P<lib>[\w-]+))?"
    r"(?P<replacing>\s+REPLACING\s+.*?)?\s*\.(?=\s|$)",
    re.I | re.S,
)
_COPY_SUFFIXES = ("", ".cpy", ".CPY", ".cob", ".COB", ".cbl", ".CBL", ".copy", ".COPY")


def _clean(text: str) -> str:
    """Source without sequence numbers, indicators and comments, as free text."""
    return "\n".join(body for _, body in _source_lines(text, "auto"))


def _find_copybook(name: str, dirs: list[Path]) -> Path:
    name = name.strip("\"'")
    for d in dirs:
        for candidate in (name, name.upper(), name.lower()):
            for suffix in _COPY_SUFFIXES:
                p = d / (candidate + suffix)
                if p.is_file():
                    return p
    raise SignatureError(f"copybook {name!r} not found in {', '.join(str(d) for d in dirs)}")


def _apply_replacing(text: str, clause: str) -> str:
    pairs = re.findall(
        r"(==.*?==|\S+)\s+BY\s+(==.*?==|\S+)", clause.strip()[len("REPLACING"):], re.I | re.S
    )
    if not pairs:
        raise SignatureError(f"cannot read COPY {clause.strip()}")
    for old, new in pairs:
        old_text = old[2:-2].strip() if old.startswith("==") else old
        new_text = new[2:-2].strip() if new.startswith("==") else new
        if old.startswith("=="):
            text = re.sub(re.escape(old_text), new_text, text, flags=re.I)
        else:
            text = re.sub(rf"(?<![\w-]){re.escape(old_text)}(?![\w-])", new_text, text, flags=re.I)
    return text


def expand_copies(text: str, dirs: list[Path], depth: int = 0) -> str:
    """Replace every ``COPY name [REPLACING ...].`` with the copybook's text."""
    if depth > 10:
        raise SignatureError("COPY statements nest more than 10 levels deep")

    def substitute(m: re.Match) -> str:
        path = _find_copybook(m.group("name"), dirs)
        body = _clean(path.read_text(encoding="utf-8", errors="replace"))
        if m.group("replacing"):
            body = _apply_replacing(body, m.group("replacing"))
        return "\n" + expand_copies(body, dirs, depth + 1) + "\n"

    return _COPY.sub(substitute, text)


def _section(text: str, header: str, enders: str) -> str:
    m = re.search(rf"\b{header}\s+SECTION\s*\.", text, re.I)
    if not m:
        return ""
    rest = text[m.end():]
    end = re.search(enders, rest, re.I)
    return rest[: end.start()] if end else rest


_DATA_ENDERS = (
    r"\b(?:FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE|REPORT|SCREEN)\s+SECTION\s*\."
    r"|\bPROCEDURE\s+DIVISION\b"
)


def _using(text: str) -> tuple[list[tuple[str, str, bool]], str | None]:
    m = re.search(r"\bPROCEDURE\s+DIVISION\b(.*?)\.(?=\s|$)", text, re.I | re.S)
    if not m:
        raise SignatureError("no PROCEDURE DIVISION header found")
    words = m.group(1).split()
    params, returning = [], None
    by, optional = "REFERENCE", False
    mode = None
    i = 0
    while i < len(words):
        w = words[i].upper().rstrip(",")
        if w == "USING":
            mode = "using"
        elif w == "RETURNING":
            mode = "returning"
        elif w == "BY" and i + 1 < len(words):
            by = words[i + 1].upper()
            i += 1
        elif w in ("REFERENCE", "VALUE", "CONTENT"):
            by = w
        elif w == "OPTIONAL":
            optional = True
        elif w in ("CHAINING",):
            raise SignatureError("PROCEDURE DIVISION CHAINING is not supported")
        elif mode == "using":
            params.append((w, by, optional))
            optional = False
        elif mode == "returning":
            returning = w
        i += 1
    return params, returning


def read_signature(
    source: str | Path,
    *,
    copy_dirs=(),
    options: Options | None = None,
) -> Signature:
    """Read PROGRAM-ID, USING parameters, their LINKAGE layouts and EXTERNAL items."""
    path = Path(source)
    dirs = [path.parent.resolve(), *[Path(d).resolve() for d in copy_dirs]]
    text = expand_copies(_clean(path.read_text(encoding="utf-8", errors="replace")), dirs)
    # only the outermost program: stop at a nested or following program
    ids = list(re.finditer(r"\bPROGRAM-ID\s*\.\s*(\"[^\"]+\"|'[^']+'|[\w-]+)", text, re.I))
    if not ids:
        raise SignatureError("no PROGRAM-ID found")
    program_id = ids[0].group(1).strip("\"'")
    if len(ids) > 1:
        text = text[: ids[1].start()]

    options = options or Options()
    linkage_text = _section(text, "LINKAGE", _DATA_ENDERS)
    linkage, link_errors = (
        Layout.records(linkage_text, format="free", options=options, lenient=True)
        if linkage_text.strip() else ({}, {})
    )
    externals = {}
    for header in ("WORKING-STORAGE", "FILE"):
        sect = _section(text, header, _DATA_ENDERS)
        if "EXTERNAL" not in sect.upper():
            continue
        layouts, _ = Layout.records(sect, format="free", options=options, lenient=True)
        externals.update({n: l for n, l in layouts.items() if l.root.external})

    raw_params, returning = _using(text)
    params = []
    for name, by, optional in raw_params:
        layout = linkage.get(name)
        error = None
        if layout is None:
            err = link_errors.get(name)
            error = str(err) if err else f"{name} is not described in the LINKAGE SECTION"
        params.append(Param(name, layout, by, optional, error))
    return Signature(program_id, params, returning, externals, linkage)
