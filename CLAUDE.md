# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python -m unittest discover -s tests                    # full suite (45 tests, no git/network needed)
cd tests && python -m unittest test_dirdiff.ExtractRisk.test_plain_level   # a single test or class
python -m unittest discover -s tests -k test_plain_level                   # or by name pattern

python -m dirdiff DIR_A DIR_B -c config.json -o report.md            # run the tool
python -m dirdiff DIR_A DIR_B -c config.json -o report.md --no-llm   # skip model analysis
```

`python -m unittest tests.test_dirdiff...` does **not** work — `tests/` has no `__init__.py`. Run
from inside `tests/` (the test file inserts the repo root into `sys.path` itself) or use `-k`.

There is no build step, no linter config, and no package metadata — the tool is copied, not installed.

## Hard constraints

These are deployment requirements, not preferences. Violating them breaks the tool's reason to exist.

- **Standard library only.** The target is an air-gapped network with no pip, no virtualenv, no
  wheels. Never add a third-party import, not even a dev-only or test-only one.
- **Python 3.8+.** No walrus, no `match`, no positional-only params.
- **Runs on Windows and Linux.** Path handling is a real concern here, not a hypothetical one — see
  `gitdiff.py`'s `_unquote`, `_fold`, `_relativize` and their tests.
- **External tools are optional.** `clang-format` and `gcc` may be absent; `warn()` and continue
  with un-normalized text rather than failing.

## Architecture

Read `README.md` first — it documents the pipeline, the config format, the report structure and the
JSON schema for users. What follows is what the README does not say.

**The core trick** (`compare.py`): `git diff` runs *twice* — once on the untouched originals, once on
rule-normalized copies in a temp directory. A file in the first set but not the second changed only
in ways the rules were told to ignore. That subtraction *is* the definition of "noise only"; there is
no separate noise detector. The three output categories are disjoint by construction because skipped
files are physically deleted from both copies before the second diff.

**Dependency direction is strictly one-way** and there are no import cycles:

```
common  ←  gitdiff, rules  ←  compare  ←  cli  →  llm, output
```

Keep it that way. `output.py` and `llm.py` are leaves that `cli` wires together.

**Each module has one documented public interface**, listed in its docstring; everything else is
underscore-prefixed and internal. When adding a function, default to underscore-prefixed and only
promote it if the module docstring's interface list changes too.

**Encapsulation that matters:** all of git's path quoting, `a/`/`b/` prefixes, temp-directory
prefixes and separator normalization live inside `gitdiff.py`. Callers only ever see plain
forward-slash relative paths. Do not leak git path formatting outward.

**The chat seam** (`llm.py`): `analyze_changes` accepts a `chat(system, user, label) -> str | None`
callable rather than building an HTTP client. `http_chat(config)` is the production adapter; tests
pass `FakeChat`. This is what makes file capping, hunk splitting and summary folding testable with no
server. Any second backend plugs in here.

**Failure policy:** a failed model call, a missing normalizer or a failing normalize step warns to
stderr and the run continues with a degraded report. Only unusable input aborts — bad directory or
unreadable config, `main` returns exit code 2. `chat` callables return `None` instead of raising.

## Conventions

- `%`-formatting throughout; no f-strings, no type annotations anywhere in `dirdiff/`. Match it.
- Module and function docstrings explain *why* a design choice was made (see `_apply_ignore_lines`,
  `_fold`, `_section_path`). Preserve that reasoning when editing; it documents decisions the code
  alone cannot.
- Tests are stdlib `unittest`, and deliberately touch no git, no subprocesses and no network. A few
  reach for underscore internals (`_relativize`, `_extract_risk`, `_split_sections`, `_program_of`) —
  that is intentional, documented in the test module docstring, and applies to path formatting and
  risk extraction, where testing only through the public surface would make failures hard to localize.
- Behavioural changes belong in `README.md` too — it is the user-facing spec, including the
  limitations section. A breaking change to the JSON output must bump `schema_version` in
  `output.py:build_json`.
