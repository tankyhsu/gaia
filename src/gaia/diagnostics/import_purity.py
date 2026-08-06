"""Best-effort static lint for the Scenario module import-purity contract (A2.1).

`gaia.starters.scenario_discovery` documents that Scenario modules listed under
`scenarios.modules` must be import-pure: at import time they may only define functions
and classes, define constants, attach decorator metadata, and import other pure modules.
They must not open network or database connections, resolve secrets, read or write
files, construct a client that needs explicit release, or start threads or event loops
-- all such resources belong in a Starter component owned by the application lifespan.

This module is the "second layer" of that contract: a static AST check that flags
*obvious* violations without importing the target module. It is deliberately narrow:

- **It is a lint, not an isolation boundary or a security control.** It only recognizes
  a fixed allowlist of well-known impure calls resolved by import source, and it can be
  defeated by indirection (dynamic `importlib.import_module`, calling through a
  locally-defined wrapper, third-party code that does I/O internally without matching
  any name in the allowlist, ...). Do not describe it, in code, docs, or CLI output, as
  providing isolation or a security boundary -- match the tone of
  `docs/施工图/09-Runtime安全边界与Sandbox.md`, which is equally explicit about what its
  own boundaries do and do not cover.
- **It does not import the module under scan.** It resolves the module's source file via
  `importlib.util.find_spec` and reads + `ast.parse`s that file directly. Note carefully:
  `find_spec("a.b.c")` still *imports* the parent packages `a` and `a.b` as an unavoidable
  side effect of Python's import machinery (it has to, to locate `c` inside `b`'s
  `__path__`) -- only the leaf module `a.b.c` itself is never imported. If a violation
  lives in a parent package's own top level rather than in the leaf scenario module, this
  scan will not catch it (and will have already executed it as a side effect of scanning
  its child). This is a known, accepted gap, not an oversight.
- **It matches by resolved import source, never by bare call name.** Matching bare names
  like `connect` or `Client` would flag a business author's own `Client` class or any
  object's `.connect()` method -- false positives that make operators disable the check
  entirely, which protects nothing. A local alias table is built from the module's
  top-level `import` / `from ... import` statements (including `as` aliases), and only
  calls that resolve, through that table, to a fully-qualified name in `IMPURE_CALLS` are
  flagged. A call whose source cannot be resolved -- a bare `Client()` with no matching
  import, `obj.connect()`, the result of a dynamic import -- is never flagged. This
  under-reporting is deliberate: see the "never by bare name" note on `IMPURE_CALLS`.
- **It only looks at module-level code.** Concretely: `ast.Module.body`, plus statements
  nested under top-level `if`/`try`/`with`/`for`/`while` blocks (ordinary control flow
  that still runs unconditionally when the module loads) -- but never inside a
  `def`/`async def`/`class` body or a `lambda`, because those do not execute until
  something later calls them; that is runtime, not import time.

Runtime monkeypatching was considered for a stronger dynamic check and rejected for this
framework. An earlier draft of A2.1 proposed patching `socket.socket.connect` and
`gaia.config.secrets.resolve_secret` for the duration of `discover_scenarios`'s import
window. That was rejected because: (a) `socket.socket.connect` is a C-level method and
monkeypatching it is not reliably intercepted across platforms/implementations; (b) the
patch is process-global -- any other thread or component active during startup is
affected, not just the module being scanned; (c) if the target module already did
`from gaia.config.secrets import resolve_secret`, patching the attribute on the original
module has no effect on the name already bound in the target's namespace; (d) it would
only catch a handful of I/O shapes while giving users the false impression that import
was genuinely sandboxed -- worse than no check at all. **Do not reintroduce process-wide
monkeypatching here, in `gaia check`, or anywhere else in the application startup path.**
If a stronger dynamic probe is ever needed, the correct design is to import the target
module inside an isolated **subprocess** and observe its behavior from the outside; the
main process only reads that subprocess's result. That is future work and is not
implemented by this module.
"""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass
from pathlib import Path

# Fully-qualified names this scan treats as import-time I/O. Extend this set only with
# fully-qualified names ("pkg.mod.symbol" or "pkg.mod.Class.method") resolved through an
# import statement -- never add a bare name ("connect", "Client", "from_url"): matching by
# bare name reintroduces exactly the false-positive problem this module exists to avoid.
IMPURE_CALLS: frozenset[str] = frozenset(
    {
        "gaia.config.secrets.resolve_secret",
        "sqlalchemy.create_engine",
        "sqlalchemy.ext.asyncio.create_async_engine",
        "httpx.Client",
        "httpx.AsyncClient",
        "redis.Redis.from_url",
        "redis.asyncio.Redis.from_url",
        "builtins.open",
    }
)

# `open(...)` resolves to `builtins.open` without any import statement. Any other name
# here would need an explicit import to resolve, so this is the only implicit entry.
_IMPLICIT_BUILTINS: dict[str, str] = {"open": "builtins.open"}

_HINTS: dict[str, str] = {
    "gaia.config.secrets.resolve_secret": (
        "Resolve this secret inside a Starter factory (ComponentScope.APPLICATION), not "
        "at scenario module import time."
    ),
    "sqlalchemy.create_engine": (
        "Create the engine inside a Starter factory so it is owned by the application "
        "lifespan (AsyncExitStack) instead of by importing this module."
    ),
    "sqlalchemy.ext.asyncio.create_async_engine": (
        "Create the async engine inside a Starter factory so it is owned by the "
        "application lifespan (AsyncExitStack) instead of by importing this module."
    ),
    "httpx.Client": (
        "Construct this client inside a Starter factory so it is released by the "
        "application lifespan instead of leaking a connection at import time."
    ),
    "httpx.AsyncClient": (
        "Construct this client inside a Starter factory so it is released by the "
        "application lifespan instead of leaking a connection at import time."
    ),
    "redis.Redis.from_url": (
        "Construct this client inside a Starter factory so it is released by the "
        "application lifespan instead of connecting at import time."
    ),
    "redis.asyncio.Redis.from_url": (
        "Construct this client inside a Starter factory so it is released by the "
        "application lifespan instead of connecting at import time."
    ),
    "builtins.open": (
        "Open files inside a function or Starter factory, not at module import time -- "
        "an import-time file handle is never closed by the application lifespan."
    ),
}

_DEFAULT_HINT = (
    "Move this call into a Starter component (ComponentScope.APPLICATION) constructed "
    "during application startup, not at scenario module import time."
)


@dataclass(frozen=True)
class PurityFinding:
    """One suspected import-time I/O call in a Scenario module.

    `symbol` is the fully-qualified name the call resolved to (e.g.
    `"gaia.config.secrets.resolve_secret"`), not the bare name written at the call site --
    the qualified form is what makes a finding actionable when the same bare name could
    come from several imports.
    """

    module: str
    line: int
    symbol: str
    hint: str


class _SkipNestedScopes(ast.NodeVisitor):
    """Base visitor that never descends into runtime-only scopes.

    `def`/`async def`/`class` bodies and `lambda` bodies do not execute when the module is
    imported -- only when something later calls the function, instantiates the class (its
    body runs once, at class-creation time, but per the A2.1 contract we deliberately treat
    class bodies as out of scope for this lint too, matching "函数体和类体内的调用一律忽略"
    in the task card), or invokes the lambda. Overriding these visit_* methods to a no-op
    (no `generic_visit` call) means the walk simply never reaches anything nested inside
    them, which also means decorator expressions on a skipped def/class are not scanned --
    an accepted narrowing, consistent with this module's under-report bias.
    """

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return


class _AliasCollector(_SkipNestedScopes):
    """Builds the `{local name: fully-qualified name}` alias table for module-level code.

    `module_aliases` covers `import x` / `import x as y` (`y` -> the dotted path bound,
    which is just the leading package name for a bare `import a.b.c`, matching how Python
    itself only binds `a` in that case). `symbol_aliases` covers `from x import y` /
    `from x import y as z`. Relative imports (`from . import y`) are skipped -- their
    absolute target cannot be resolved from the AST alone, and an unresolved source must
    never be flagged. `local_names` collects names bound by top-level `def`/`class`/
    assignment so a call can be recognized as shadowed by a local definition rather than
    misresolved through a same-named import or builtin.
    """

    def __init__(self) -> None:
        self.module_aliases: dict[str, str] = {}
        self.symbol_aliases: dict[str, str] = {}
        self.local_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if alias.asname:
                self.module_aliases[alias.asname] = alias.name
            else:
                top_level = alias.name.split(".")[0]
                self.module_aliases[top_level] = top_level

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.level != 0 or node.module is None:
            return  # relative import: absolute source cannot be resolved from the AST.
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            self.symbol_aliases[local_name] = f"{node.module}.{alias.name}"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.local_names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.local_names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.local_names.add(node.name)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.local_names.add(target.id)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if isinstance(node.target, ast.Name):
            self.local_names.add(node.target.id)


class _CallCollector(_SkipNestedScopes):
    """Collects every `ast.Call` reachable from module-level code (see `_SkipNestedScopes`)."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self.calls.append(node)
        self.generic_visit(node)


def _attribute_chain(node: ast.expr) -> list[str] | None:
    """Flatten `a.b.c` into `["a", "b", "c"]`, or `None` if the base is not a plain name."""

    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return parts


def _resolve_call(
    call: ast.Call,
    module_aliases: dict[str, str],
    symbol_aliases: dict[str, str],
    local_names: set[str],
) -> str | None:
    """Resolve a call's callee to a fully-qualified name, or `None` if it cannot be resolved.

    Returning `None` for anything ambiguous or locally shadowed is the point: an unresolved
    call is never flagged, which is what keeps this scan from false-positiving on business
    code (`obj.connect()`, a locally-defined `Client`, ...).
    """

    func = call.func
    if isinstance(func, ast.Name):
        if func.id in local_names:
            return None  # shadowed by a local def/class/assignment, not the import.
        if func.id in symbol_aliases:
            return symbol_aliases[func.id]
        return _IMPLICIT_BUILTINS.get(func.id)
    if isinstance(func, ast.Attribute):
        chain = _attribute_chain(func)
        if chain is None:
            return None
        head, *rest = chain
        if head in local_names:
            return None
        base = module_aliases.get(head)
        if base is None:
            return None
        return ".".join([base, *rest])
    return None


def _hint_for(symbol: str) -> str:
    return _HINTS.get(symbol, _DEFAULT_HINT)


def scan_module_purity(module_name: str) -> tuple[PurityFinding, ...]:
    """Flag obvious import-time I/O in `module_name` without importing it.

    Locates the module's source via `importlib.util.find_spec` (which, unavoidably,
    imports `module_name`'s parent packages -- see the module docstring), reads and
    `ast.parse`s the file, and flags module-level calls that resolve, via the module's own
    `import`/`from ... import` statements, to a name in `IMPURE_CALLS`. Never raises: any
    condition that prevents a confident answer (module/spec not found, no readable source,
    a syntax error in the target file) results in an empty tuple rather than an exception
    or a guess, consistent with this scan's "never report what it cannot resolve" design.
    """

    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError, AttributeError, TypeError):
        return ()
    if spec is None or spec.origin is None:
        return ()
    origin = Path(spec.origin)
    if origin.suffix != ".py":
        return ()  # compiled/namespace/frozen entries have no Python source to parse.
    try:
        source = origin.read_text(encoding="utf-8")
    except OSError:
        return ()
    try:
        tree = ast.parse(source, filename=str(origin))
    except SyntaxError:
        return ()

    aliases = _AliasCollector()
    aliases.visit(tree)
    calls = _CallCollector()
    calls.visit(tree)

    findings: list[PurityFinding] = []
    for call in calls.calls:
        resolved = _resolve_call(
            call, aliases.module_aliases, aliases.symbol_aliases, aliases.local_names
        )
        if resolved is None or resolved not in IMPURE_CALLS:
            continue
        findings.append(
            PurityFinding(
                module=module_name,
                line=call.lineno,
                symbol=resolved,
                hint=_hint_for(resolved),
            )
        )
    findings.sort(key=lambda finding: finding.line)
    return tuple(findings)
