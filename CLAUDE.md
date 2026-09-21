# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DMOJ judge-server: the grading backend for the DMOJ online judge. It connects to a
DMOJ site instance, receives submissions, compiles/runs untrusted user code inside a
ptrace/seccomp sandbox (`cptbox`), and reports results back over a custom TCP protocol.
Also ships `dmoj-cli` for local/offline testing of problems without a site connection.

Not supported on Windows. First-class support is Debian Linux; FreeBSD is also supported
with reduced runtime coverage.

## Environment

**This project uses a `uv`-managed virtualenv at `.venv/` — there is no `pip` binary inside
it.** For all Python work:

```
uv run python ...          # run a script/module in the project venv
uv pip install -e .[test]  # install/reinstall the package + test deps into .venv
uv pip list                 # inspect installed packages
```

Building the C/C++/Cython extensions (`cptbox`, `checkers/_checker`) requires Cython and a
C++ compiler, plus `libseccomp-dev` on Linux (`procstat` lib on FreeBSD). Install with:

```
uv pip install cython
uv pip install -e .[test]
```

`DMOJ_TARGET_ARCH` can override the `-march` used to compile the sandbox (relevant on ARM,
where a target isn't inferred automatically and a slow generic build is produced otherwise).
`DMOJ_PARALLEL` controls the number of parallel compile jobs used by `setup.py`.

Any change to `dmoj/cptbox/*.pyx/.pxd/.cpp/.h` or `dmoj/checkers/_checker.c` requires
re-running the build (`uv pip install -e .`) to take effect, since these are compiled
extensions loaded as `dmoj.cptbox._cptbox` / `dmoj.checkers._checker`.

## Common commands

```
# Run the unit test suite (dmoj/tests/)
uv run python -m unittest discover dmoj/tests/

# Run a single test module / class / method
uv run python -m unittest dmoj.tests.test_problem
uv run python -m unittest dmoj.tests.test_problem.ProblemTestCase.test_something

# Lint (flake8 config lives in .flake8; excludes ./testsuite)
uv run flake8

# Format (Black; line-length 120, single quotes preferred — see pyproject.toml)
uv run black .

# Type-check
uv run mypy dmoj

# Format the C/C++ sandbox sources (.clang-format: LLVM-based, 120 col)
find dmoj/ \( -name '*.h' -or -name '*.cpp' -or -name '*.c' \) -not -name _cptbox.cpp | xargs clang-format -i

# Full executor self-test suite (compiles & runs a "Hello, World!" in every configured
# language executor — this is what CI runs inside the runtimes-docker image, not
# something that generally works outside it)
uv run python .docker.test.py
```

CI (`.github/workflows/build.yml`) runs flake8 + black (via flake8-black), clang-format,
mypy, an sdist build/install smoke test, and the executor self-tests inside the
`dmoj/runtimes-tier3` Docker image across Python 3.7–3.11 on amd64 and arm64. There is no
useful way to run the full executor test matrix locally without that Docker image, since it
depends on dozens of language runtimes being installed.

`dmoj/tests/` (plain `unittest`) covers judge-internal logic (checkers, config parsing,
control API, filesystem policies, glob matching, the int-overflow patch, memory-backed I/O,
etc.) and runs without any language runtimes installed. The separate `testsuite` submodule
referenced conceptually in CI (declared via `.gitmodules` as `java_sandbox`, and via
`dmoj/testsuite.py`'s problem-driven test runner) is a *problem repository* used to
exercise the judge end-to-end against real problems — distinct from `dmoj/tests/`.

## Architecture

### Entry points
- `dmoj/judge.py` (`dmoj` console script) — connects to a DMOJ site over the network
  protocol and grades submissions it receives (`ClassicJudge`).
- `dmoj/cli.py` (`dmoj-cli` console script) — local/offline judge with an interactive
  shell (see `dmoj/commands/`) for testing problems without a site.
- `dmoj/testsuite.py` — drives the judge against a directory of problems + expected
  results (used with the external `testsuite` problem repo, not `dmoj/tests/`).
- `dmoj/executors/autoconfig.py` (`dmoj-autoconf` console script) — probes the system for
  installed language runtimes and writes the resulting config into `judge.yml`.

### Grading pipeline (submission lifecycle)
`Judge` (in `judge.py`) receives a `Submission` from the packet layer and spawns a
`JudgeWorker`, which runs grading in a **separate process** (`multiprocessing`), talking
back to the parent over a `Pipe` using a small IPC protocol (the `IPC` enum: HELLO,
COMPILE_ERROR, RESULT, BATCH_BEGIN/END, GRADING_BEGIN/END, etc). This isolates a crashing
grading process from the long-lived judge daemon. Within the worker:

1. `Problem` (`problem.py`) loads the problem's `init.yml`/config and test case data
   (`TestCase` / `BatchedTestCase`, batches can declare dependencies on other batches for
   short-circuiting).
2. `problem.grader_class` instantiates a grader (`dmoj/graders/`), which compiles the
   submission via the appropriate `Executor` (`dmoj/executors/`).
3. For each test case, the grader launches the compiled/interpreted submission inside the
   sandbox and produces a `Result` (`result.py`) with status flags (AC/WA/TLE/MLE/RTE/IR/...).
4. Results stream back through the IPC pipe to `Judge`, which forwards them to the site via
   `packet.PacketManager` (`packet.py`).

Short-circuiting logic (skip remaining cases in a batch/problem after a failure) lives in
`JudgeWorker._grade_cases` in `judge.py`.

### `dmoj/cptbox` — the sandbox
A ptrace + seccomp-bpf sandbox for running untrusted code, implemented as a Cython
extension (`_cptbox.pyx`) over C++ (`ptproc.cpp`, `helper.cpp`, and per-arch ptrace
debuggers `ptdebug_*.cpp/h` for x86/x64/arm/arm64/FreeBSD-x64). `isolate.py` builds an
`IsolateTracer` from filesystem access rules (`filesystem_policies.py`: `ExactFile`,
`ExactDir`, `RecursiveDir`) and per-syscall handlers (`handlers.py`); `tracer.py` wraps
`TracedPopen`, the sandboxed subprocess. Syscall number tables per architecture live under
`syscalls/*.tbl` and are regenerated by `syscalls/generate.py` (there's a scheduled GitHub
Action, `update-syscalls.yml`, that runs this and opens a PR). Any edit to the `.pyx`/C++/
headers needs a rebuild (see Environment section) before it's picked up.

### `dmoj/executors` — language runtimes
Executor class hierarchy: `BaseExecutor` → `ScriptExecutor`/`CompiledExecutor` →
language-specific subclasses (e.g. `CompiledExecutor` → `CLikeExecutor` → `C.py`/`CPP*.py`;
`ScriptExecutor` → `PythonExecutor` → `PY2.py`/`PY3.py`/`PYPY.py`). Each language lives in
its own file named after the DMOJ language code (e.g. `CPP20.py`, `JAVA8.py`), auto-
discovered by filename via `dmoj/executors/__init__.py:get_available()` (regex-matched
`[A-Z0-9]+.py`, excludes `_unsupported_executors`). An executor defines how to compile
(if needed), the sandboxed filesystem/syscall policy it needs on top of `BASE_FILESYSTEM`,
its `command`/`command_paths` (used by `autoconfig.py` to locate the runtime binary), a
`test_program` used for the self-test DMOJ runs at judge startup, and `get_cmdline()` to
build the sandboxed invocation. To add a new language: create `dmoj/executors/<CODE>.py`
subclassing the closest existing base class and follow an existing similar-language
executor as a template — no registration step needed beyond the file existing.

### `dmoj/graders` — grading strategies
- `standard.py` — classic input/output diffing via a `Checker` (see below).
- `interactive.py` — submission talks to a judge-provided interactor process over
  stdin/stdout.
- `signature.py` — submission provides a function called from grader-supplied harness code
  (function-signature-style problems).
- `bridged.py` — grader delegates checking logic to code shipped with the problem itself
  (a checker binary/script rather than a built-in one).
- `custom.py` — problem supplies its own full custom grader.
All extend `BaseGrader` (`graders/base.py`), whose `grade(case) -> Result` is the core
per-test-case entry point.

### `dmoj/checkers` — output comparison
Used by `standard`/`bridged` graders to compare expected vs. actual output:
`identical`, `standard` (token-based), `floats`/`floatsabs`/`floatsrel`, `linecount`,
`linematches`, `sorted`, `unordered`, `rstripped`, `easy`. `_checker.c` is a native
(C) implementation of the hot-path standard/token comparison for performance; if it fails
to build, `judge.py:sanity_check()` warns and falls back to the slower pure-Python
`standard.py` implementation.

### `dmoj/contrib`
Site-specific submission-format adapters (e.g. `coci.py`, `peg.py`, `testlib.py` for
testlib.h-based checkers) beyond the `default.py` DMOJ format, selected per-problem.
Loaded via `contrib.load_contrib_modules()`.

### Other core modules
- `judgeenv.py` — loads/holds judge configuration (`judge.yml`), problem directory
  discovery, environment-derived settings (time/memory limits, excluded executors, etc).
- `packet.py` — the wire protocol/connection to the DMOJ site (`PacketManager`).
- `result.py` — `Result`/`CheckerResult` value objects and status-flag bitmask (AC, WA,
  TLE, MLE, RTE, IR, SC=short-circuited, OLE, ...).
- `control.py` — HTTP control API (`JudgeControlRequestHandler`) for out-of-band judge
  control, when `-a`/`-A` is passed to `dmoj`.
- `monitor.py` — watches problem directories (via `watchdog`) and triggers problem-set
  updates pushed to the site.

## Code style notes

- Black formatting, 120-column lines, **single quotes preferred** (`skip-string-normalization`
  is off but Black is configured for single quotes via project convention — see
  `pyproject.toml`); import order via `flake8-import-order` (pycharm style,
  `application-import-names = dmoj`).
- `dmoj/cptbox/{compiler_isolate,isolate,tracer}.py` intentionally use `import *` (flake8
  F403/F405 explicitly ignored for these files).
- Several historical commits are excluded from `git blame` via `.git-blame-ignore-revs`
  (mass reformatting commits) — prefer `git blame --ignore-revs-file .git-blame-ignore-revs`.
