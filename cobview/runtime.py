"""Call GnuCOBOL programs in-process, on memory that Python owns.

    prog = cobview.Program.from_source("LIVECALC.cbl")
    rec = cobview.view(bytearray(layout.size), layout)
    prog(rec)          # COBOL works on rec's bytes through its LINKAGE SECTION

Python allocates the record; the COBOL program receives its address BY
REFERENCE, exactly as if another COBOL program had CALLed it.  Nothing is
copied in either direction, and the program's WORKING-STORAGE keeps its
values from one call to the next until :meth:`Program.cancel`.

Two things in libcob are hostile to a host process, and this module
neutralises both:

* ``cob_init`` installs C signal handlers (SIGINT, SIGSEGV, ...).  They are
  saved before and restored right after, so Ctrl-C still raises
  ``KeyboardInterrupt``.
* ``STOP RUN`` and runtime errors tear the COBOL runtime down.  Calls go
  through ``cob_call_with_exception_check`` so they become Python
  exceptions instead of ``exit()``; afterwards the runtime refuses further
  calls rather than crashing.  :func:`compile` also rewrites ``STOP RUN``
  to ``GOBACK`` with COBOL's own ``REPLACE`` statement, so legacy programs
  can be embedded without editing them.
"""

from __future__ import annotations

import atexit
import ctypes
import ctypes.util
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .copybook import Layout
from .source import Signature, SignatureError, read_signature
from .view import Record, Records, view

__all__ = [
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
]


class CobolError(RuntimeError):
    """Base class for errors raised by the COBOL runtime bridge."""


class CompileError(CobolError):
    """cobc rejected the program.  ``stderr`` holds the compiler output."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message + ("\n" + stderr.strip() if stderr.strip() else ""))
        self.stderr = stderr


@dataclass
class Result:
    """What a COBOL call produced."""

    return_code: int
    display: list[str] = field(default_factory=list)  # DISPLAY output (stdout)
    syserr: list[str] = field(default_factory=list)  # DISPLAY UPON SYSERR, libcob messages
    captured: bool = False


class CobolStopRun(CobolError):
    """The program executed STOP RUN.  ``exit_code`` is its status."""

    def __init__(self, exit_code: int, result: Result | None = None):
        detail = _detail(result)
        super().__init__(
            f"COBOL program executed STOP RUN (status {exit_code}); the COBOL runtime "
            "has ended in this process. Compile with stop_run='goback' to avoid this." + detail
        )
        self.exit_code = exit_code
        self.result = result


class CobolRuntimeError(CobolError):
    """libcob reported a runtime error."""

    def __init__(self, exit_code: int, result: Result | None = None):
        detail = _detail(result) or " Details are on stderr."
        super().__init__(
            f"COBOL runtime error (libcob exit code {exit_code}); the COBOL runtime "
            "has ended in this process." + detail
        )
        self.exit_code = exit_code
        self.result = result


class ReturnCodeError(CobolError):
    """A program returned a RETURN-CODE listed in ``errors=``.

    Subclass it to give business outcomes their own exception types.
    """

    def __init__(self, message: str = "", *, program: str = "", result: Result | None = None):
        super().__init__(message)
        self.program = program
        self.result = result
        self.return_code = result.return_code if result else None


def _detail(result: Result | None) -> str:
    if result is None or not result.captured or not result.syserr:
        return ""
    return "\nlibcob said: " + "\n".join(result.syserr)


# ---------------------------------------------------------------------------
# libcob runtime
# ---------------------------------------------------------------------------

_SIGNALS = [
    getattr(signal, name)
    for name in ("SIGINT", "SIGHUP", "SIGQUIT", "SIGTERM", "SIGPIPE", "SIGIO",
                 "SIGSEGV", "SIGBUS", "SIGFPE", "SIGEMT")
    if hasattr(signal, name)
]
_SIGACTION_SIZE = 512  # larger than struct sigaction on every supported OS


def _find_libcob() -> str:
    explicit = os.environ.get("COBVIEW_LIBCOB")
    if explicit:
        return explicit
    found = ctypes.util.find_library("cob")
    if found:
        return found
    cobc = shutil.which("cobc")
    if cobc:
        prefix = Path(cobc).resolve().parent.parent
        for pattern in ("lib/libcob.so*", "lib64/libcob.so*", "lib/libcob*.dylib"):
            hits = sorted(prefix.glob(pattern))
            if hits:
                return str(hits[0])
    raise CobolError(
        "libcob (the GnuCOBOL runtime) was not found; install GnuCOBOL or set COBVIEW_LIBCOB"
    )


class Runtime:
    """The process-wide GnuCOBOL runtime.  Use :meth:`get`; there is only one."""

    _instance: "Runtime | None" = None
    _create_lock = threading.Lock()

    def __init__(self, libcob_path: str | None = None):
        self._lock = threading.RLock()
        self._busy = False
        self.ended: str | None = None
        self._modules: dict[Path, ctypes.CDLL] = {}
        self._programs: dict[str, Path] = {}
        self._externals: dict[str, tuple[int, str]] = {}  # name -> (size, declared by)
        self._libc = ctypes.CDLL(None)

        libc = ctypes.CDLL(None)
        saved = {}
        for sig in _SIGNALS:
            buf = ctypes.create_string_buffer(_SIGACTION_SIZE)
            if libc.sigaction(sig, None, buf) == 0:
                saved[sig] = buf
        self.libcob = ctypes.CDLL(libcob_path or _find_libcob(), mode=ctypes.RTLD_GLOBAL)
        self.libcob.cob_init(0, None)
        for sig, buf in saved.items():
            libc.sigaction(sig, buf, None)

        call = self.libcob.cob_call_with_exception_check
        call.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        call.restype = ctypes.c_int
        self._call = call
        self.libcob.cob_last_exit_code.restype = ctypes.c_int
        self.libcob.cob_cancel.argtypes = [ctypes.c_char_p]
        self.libcob.cob_external_addr.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.libcob.cob_external_addr.restype = ctypes.c_void_p
        atexit.register(self._tidy)

    @classmethod
    def get(cls) -> "Runtime":
        with cls._create_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _tidy(self) -> None:
        if self.ended is None:
            try:
                self.libcob.cob_tidy()
            except Exception:  # pragma: no cover - best effort at exit
                pass

    def load(self, path: str | Path) -> ctypes.CDLL:
        path = Path(path).resolve()
        if path not in self._modules:
            if not path.exists():
                raise FileNotFoundError(path)
            self._modules[path] = ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
        return self._modules[path]

    def register(self, name: str, module: Path) -> None:
        """Program names are global in a COBOL run unit: refuse duplicates."""
        key = name.upper()
        owner = self._programs.setdefault(key, module)
        if owner != module:
            raise CobolError(
                f"a program named {name!r} is already loaded from {owner}; COBOL "
                "program names are global in a run unit, so a second copy would never be called"
            )

    def call(self, name: str, addresses: list[int], *, capture: bool = False) -> Result:
        """CALL program ``name`` USING the given addresses.

        With ``capture=True`` everything the program DISPLAYs (and anything
        libcob prints to stderr) is collected in the :class:`Result` instead
        of reaching the terminal.
        """
        with self._lock:
            self._check_alive()
            if self._busy:
                raise CobolError("nested COBOL calls from Python are not supported yet")
            argv = (ctypes.c_void_p * len(addresses))(*addresses) if addresses else None
            self._busy = True
            capturer = _Capture() if capture else None
            try:
                if capturer:
                    capturer.start(self._libc)
                status = self._call(name.encode("ascii"), len(addresses), argv)
            finally:
                if capturer:
                    capturer.stop(self._libc)
                self._busy = False
            result = Result(
                self.libcob.cob_last_exit_code(),
                capturer.out if capturer else [],
                capturer.err if capturer else [],
                captured=capture,
            )
            if status == 0:
                return result
            if status == 1:
                self.ended = "STOP RUN"
                raise CobolStopRun(result.return_code, result)
            self.ended = "runtime error"
            raise CobolRuntimeError(status, result)

    def _check_alive(self) -> None:
        if self.ended:
            raise CobolError(
                f"the COBOL runtime ended earlier ({self.ended}); "
                "start a new Python process to call COBOL again"
            )

    def declare_external(self, name: str, size: int, owner: str) -> None:
        """Remember an EXTERNAL item's size so mismatches fail in Python, not in libcob.

        libcob ends the whole process when two declarations of one EXTERNAL
        item disagree on its size.
        """
        key = name.upper().replace("-", "_")
        known = self._externals.get(key)
        if known and known[0] != size:
            raise CobolError(
                f"EXTERNAL {name} is {known[0]} bytes in {known[1]} but {size} bytes in {owner}"
            )
        self._externals.setdefault(key, (size, owner))

    def external(self, name: str, size: int) -> int:
        """Address of the EXTERNAL item ``name`` (created now if no program has yet)."""
        with self._lock:
            self._check_alive()
            self.declare_external(name, size, "Python")
            key = name.upper().replace("-", "_")
            return self.libcob.cob_external_addr(key.encode("ascii"), size)

    def cancel(self, name: str) -> None:
        with self._lock:
            if not self.ended:
                self.libcob.cob_cancel(name.encode("ascii"))


# ---------------------------------------------------------------------------
# compiling
# ---------------------------------------------------------------------------

_PROGRAM_ID = re.compile(r"PROGRAM-ID\s*\.\s*(\"[^\"]+\"|'[^']+'|[A-Za-z0-9][\w-]*)", re.I)
_STOP_RUN_GUARD = "       REPLACE ==STOP RUN== BY ==GOBACK==.\n"


def program_id(source_text: str) -> str:
    m = _PROGRAM_ID.search(source_text)
    if not m:
        raise CompileError("no PROGRAM-ID found in the source")
    return m.group(1).strip("\"'")


def _cache_dir() -> Path:
    base = os.environ.get("COBVIEW_CACHE")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg) / "cobview" if xdg else Path.home() / ".cache" / "cobview"


def compile(  # noqa: A001 - mirrors the cobc verb
    source: str | Path,
    *,
    output: str | Path | None = None,
    copy_dirs=(),
    stop_run: str = "goback",
    extra_args=(),
    cobc: str = "cobc",
) -> Path:
    """Compile a COBOL source file into a loadable module (``cobc -m``).

    ``stop_run="goback"`` (the default) inserts
    ``REPLACE ==STOP RUN== BY ==GOBACK==.`` before the source so the
    program returns to Python instead of ending the process.  Use
    ``stop_run="keep"`` to compile the source untouched.  Results are
    cached by content, so calling this again is cheap.
    """
    if stop_run not in ("goback", "keep"):
        raise ValueError("stop_run must be 'goback' or 'keep'")
    exe = shutil.which(cobc)
    if exe is None:
        raise CompileError(f"{cobc} not found; install GnuCOBOL")
    source = Path(source).resolve()
    text = source.read_text(encoding="utf-8", errors="replace")
    includes = [source.parent, *[Path(d).resolve() for d in copy_dirs]]
    args = ["-m", *[f"-I{d}" for d in includes], *extra_args]

    key = hashlib.sha256()
    for part in (text, stop_run, repr(args), _cobc_version(exe)):
        key.update(part.encode())
    for d in includes:  # copybooks can change without the source changing
        for cpy in sorted(d.glob("*.cpy")):
            key.update(cpy.name.encode() + cpy.read_bytes())
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    if output is None:
        output = _cache_dir() / key.hexdigest()[:16] / (source.stem + suffix)
    output = Path(output).resolve()
    if output.exists() and output.with_suffix(".key").exists() and (
        output.with_suffix(".key").read_text() == key.hexdigest()
    ):
        return output
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cobview-") as tmp:
        compiled_source = source
        if stop_run == "goback":
            compiled_source = Path(tmp) / source.name
            compiled_source.write_text(_STOP_RUN_GUARD + text, encoding="utf-8")
        proc = subprocess.run(
            [exe, *args, "-o", str(output), str(compiled_source)],
            capture_output=True,
            text=True,
            cwd=tmp,
        )
    if proc.returncode != 0:
        note = " (line numbers are +1: cobview added a REPLACE line)" if stop_run == "goback" else ""
        raise CompileError(f"cobc failed for {source.name}{note}", proc.stderr + proc.stdout)
    output.with_suffix(".key").write_text(key.hexdigest())
    return output


_VERSION_CACHE: dict[str, str] = {}


def _cobc_version(exe: str) -> str:
    if exe not in _VERSION_CACHE:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
        _VERSION_CACHE[exe] = out.splitlines()[0] if out else "unknown"
    return _VERSION_CACHE[exe]


# ---------------------------------------------------------------------------
# programs
# ---------------------------------------------------------------------------


def _c_name(program: str) -> str:
    """GnuCOBOL's C symbol for a program name: '-' becomes '__'."""
    return program.replace("-", "__")


class Program:
    """A COBOL program you can call like a Python function.

    Arguments are passed BY REFERENCE: each must be writable memory - a
    :class:`Record`, :class:`Records`, ``bytearray``, writable
    ``memoryview``/``mmap``, or a ctypes object.

    ``using=[layout, ...]`` checks argument sizes before COBOL touches them;
    :meth:`from_source` reads them from the LINKAGE SECTION automatically.
    ``errors={4: SomeError}`` turns RETURN-CODE values into exceptions
    (``errors="nonzero"`` raises :class:`ReturnCodeError` for any non-zero).
    """

    def __init__(self, module: str | Path, name: str | None = None, *, using=None,
                 errors=None, signature: Signature | None = None,
                 runtime: Runtime | None = None):
        self.runtime = runtime or Runtime.get()
        self.module = Path(module).resolve()
        handle = self.runtime.load(self.module)
        candidates = [name] if name else [self.module.stem, self.module.stem.upper(),
                                           self.module.stem.lower()]
        for cand in candidates:
            if hasattr(handle, _c_name(cand)):
                self.name = cand
                break
        else:
            raise CobolError(
                f"{self.module.name} has no COBOL program named "
                f"{name or self.module.stem!r}; pass name= with its PROGRAM-ID"
            )
        self.runtime.register(self.name, self.module)
        self.signature = signature
        if signature is not None:
            for ext_name, layout in signature.externals.items():
                self.runtime.declare_external(ext_name, layout.size, self.name)
        if using is None and signature is not None and signature.params and signature.complete:
            using = [p.layout for p in signature.params]
        self.using = list(using) if using is not None else None
        self.errors = _check_errors(errors)

    @classmethod
    def from_source(cls, source: str | Path, *, using=None, errors=None,
                    copy_dirs=(), **compile_options) -> "Program":
        """Compile (cached) and load ``source``.

        The PROGRAM-ID names the program, and the PROCEDURE DIVISION USING
        header plus the LINKAGE SECTION give its :attr:`signature`, so
        arguments are size-checked and :meth:`new_args` can allocate them.
        """
        path = Path(source)
        try:
            signature = read_signature(path, copy_dirs=copy_dirs)
            name = signature.program_id
        except SignatureError:
            signature = None
            name = program_id(path.read_text(encoding="utf-8", errors="replace"))
        module = compile(path, copy_dirs=copy_dirs, **compile_options)
        return cls(module, name, using=using, errors=errors, signature=signature)

    # -- calling ------------------------------------------------------------

    def __call__(self, *args) -> int:
        """CALL the program USING ``args``; returns its RETURN-CODE."""
        return self.run(*args).return_code

    def run(self, *args, capture: bool = False) -> Result:
        """Like calling the program, but returns a :class:`Result`.

        ``capture=True`` collects the program's DISPLAY output in
        ``result.display`` (and DISPLAY UPON SYSERR in ``result.syserr``).
        """
        if self.using is not None and len(args) != len(self.using):
            raise TypeError(
                f"{self.name} takes {len(self.using)} arguments (USING), got {len(args)}"
            )
        if self.signature is not None and any(p.by == "VALUE" for p in self.signature.params):
            raise CobolError(f"{self.name} has BY VALUE parameters, which are not supported yet")
        keep, addresses = [], []
        for i, arg in enumerate(args):
            buf = _writable(arg, f"argument {i + 1}")
            if self.using is not None:
                need = self.using[i].size
                if ctypes.sizeof(buf) < need:
                    raise ValueError(
                        f"argument {i + 1} has {ctypes.sizeof(buf)} bytes; "
                        f"{self.using[i].name} needs {need}"
                    )
            keep.append(buf)
            addresses.append(ctypes.addressof(buf))
        try:
            result = self.runtime.call(self.name, addresses, capture=capture)
        finally:
            del keep  # release buffer exports so mmaps can close
        self._raise_for(result)
        return result

    def _raise_for(self, result: Result) -> None:
        code = result.return_code
        if self.errors is None:
            return
        if self.errors == "nonzero":
            if code != 0:
                raise ReturnCodeError(f"{self.name} returned RETURN-CODE {code}",
                                      program=self.name, result=result)
            return
        exc_type = self.errors.get(code)
        if exc_type is None:
            return
        message = f"{self.name} returned RETURN-CODE {code}"
        if isinstance(exc_type, type) and issubclass(exc_type, ReturnCodeError):
            raise exc_type(message, program=self.name, result=result)
        exc = exc_type(message)
        for attr, value in (("program", self.name), ("result", result), ("return_code", code)):
            try:
                setattr(exc, attr, value)
            except AttributeError:
                pass
        raise exc

    # -- arguments and shared storage ---------------------------------------

    def new_args(self, *, arithmetic: str = "strict") -> tuple[Record, ...]:
        """Fresh, zero-filled records for every USING parameter, typed by its layout."""
        if self.using is None:
            raise CobolError(
                f"{self.name}'s parameters are unknown; load it with from_source() or pass using="
            )
        return tuple(view(bytearray(layout.size), layout, arithmetic=arithmetic)
                     for layout in self.using)

    def external(self, name: str, *, arithmetic: str = "strict") -> Record:
        """A live view of one of this program's EXTERNAL items, by its COBOL name."""
        key = name.upper().replace("_", "-")
        if self.signature is None or key not in self.signature.externals:
            known = ", ".join(self.signature.externals) if self.signature else "unknown"
            raise KeyError(f"{self.name} declares no EXTERNAL item {name!r} (it has: {known})")
        return external(key, self.signature.externals[key],
                        arithmetic=arithmetic, runtime=self.runtime)

    def cancel(self) -> None:
        """CANCEL the program: its WORKING-STORAGE starts fresh on the next call."""
        self.runtime.cancel(self.name)

    def __repr__(self) -> str:
        sig = f" {self.signature}" if self.signature else ""
        return f"<Program {self.name} from {self.module.name}{sig}>"


def _check_errors(errors):
    if errors is None or errors == "nonzero":
        return errors
    if not isinstance(errors, dict):
        raise TypeError("errors must be a dict of {return_code: exception class} or 'nonzero'")
    for code, exc in errors.items():
        if not isinstance(code, int):
            raise TypeError(f"errors keys are RETURN-CODE integers, got {code!r}")
        if not (isinstance(exc, type) and issubclass(exc, BaseException)):
            raise TypeError(f"errors[{code}] must be an exception class, got {exc!r}")
    return dict(errors)


def external(name: str, layout: Layout, *, arithmetic: str = "strict",
             runtime: Runtime | None = None) -> Record:
    """A live, zero-copy view of COBOL ``EXTERNAL`` storage named ``name``.

    EXTERNAL items are shared by name across the whole run unit, so every
    COBOL program that declares ``01 name EXTERNAL`` sees the same bytes as
    this view - no arguments needed.  The layout's size must match the
    COBOL declaration.
    """
    runtime = runtime or Runtime.get()
    address = runtime.external(name, layout.size)
    memory = (ctypes.c_ubyte * layout.size).from_address(address)
    return view(memory, layout, arithmetic=arithmetic)


class _Capture:
    """Redirect file descriptors 1 and 2 into reusable temporary files for one call."""

    _files: list | None = None  # shared by all captures; calls are serialised

    def start(self, libc) -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        libc.fflush(None)
        if _Capture._files is None:
            _Capture._files = [tempfile.TemporaryFile(), tempfile.TemporaryFile()]
        for f in _Capture._files:
            f.seek(0)
            f.truncate()
        self._saved = [os.dup(1), os.dup(2)]
        os.dup2(_Capture._files[0].fileno(), 1)
        os.dup2(_Capture._files[1].fileno(), 2)

    def stop(self, libc) -> None:
        libc.fflush(None)
        os.dup2(self._saved[0], 1)
        os.dup2(self._saved[1], 2)
        for fd in self._saved:
            os.close(fd)
        texts = []
        for f in _Capture._files:
            f.seek(0)
            texts.append(f.read().decode("utf-8", errors="replace"))
        self.out = texts[0].splitlines()
        self.err = [line for line in texts[1].splitlines() if line.strip()]


def _writable(arg, what: str):
    """A ctypes view of ``arg``'s memory, refusing anything COBOL must not write to."""
    if isinstance(arg, Record):
        mv = arg.raw
    elif isinstance(arg, Records):
        mv = arg.buffer
    elif isinstance(arg, (ctypes._SimpleCData, ctypes.Array, ctypes.Structure, ctypes.Union)):
        return (ctypes.c_char * ctypes.sizeof(arg)).from_address(ctypes.addressof(arg))
    elif isinstance(arg, (bytes, str)):
        raise TypeError(f"{what} is read-only ({type(arg).__name__}); use a bytearray or a view")
    else:
        mv = memoryview(arg)
    if mv.readonly:
        raise TypeError(f"{what} is read-only memory; COBOL may write to it")
    if not mv.c_contiguous:
        raise TypeError(f"{what} is not contiguous memory")
    mv = mv.cast("B") if mv.format != "B" or mv.ndim != 1 else mv
    if len(mv) == 0:
        raise ValueError(f"{what} is empty")
    return (ctypes.c_char * len(mv)).from_buffer(mv)
