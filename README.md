# dirdiff — rule-based directory comparison

Compares two source directories and separates **substantive change** from **noise**:
formatting differences, comments, whitespace, and generated timestamps or build
numbers. Only what survives the filter is sent to a language model for analysis.

## What it does

The pipeline runs in two stages.

**Stage 1 — deterministic filtering (no model).**
Both directories are copied to a temporary directory. Rules from the config file are
applied to the copies: files not worth comparing are deleted, source files are
normalized (comments stripped, formatting flattened), and generated lines are replaced
with a fixed token on both sides. Then `git diff` runs on the normalized copies.

**Stage 2 — model analysis.**
Only the files still differing after normalization are sent to the model, one at a
time, followed by an executive summary built from all the per-file analyses. The
result is a Markdown report.

That separation is the whole point: the model does not spend its context window on
brace placement, and whoever reads the report does not have to filter it out by hand.

### How files are classified

| Classification | Meaning |
|---|---|
| added / deleted / modified / renamed | Real change — survived normalization, sent for analysis |
| noise only | The file differs between directories, but is identical after normalization |
| skipped | Matched a rule with `skip: true` — never compared at all |

## Project layout

```
dirdiff/
  __main__.py   entry point for `python3 -m dirdiff`
  cli.py        argument parsing and wiring
  compare.py    the two-diff pipeline and classification — the core algorithm
  rules.py      the filter stage
  gitdiff.py    what changed between two directories
  llm.py        model analysis of the real changes
  output.py     Markdown, HTML and JSON rendering
  common.py     warning reporting
config.json     example config
tests/          unit tests, stdlib unittest only
```

Each module is designed around a small interface with the complexity behind it.
The whole public surface of the package is:

| Module | Public interface |
|---|---|
| `compare` | `compare(dir_a, dir_b, rules) -> Comparison` |
| `gitdiff` | `changed_files(...)`, `diff_sections(...)` |
| `rules` | `prepare_copy(...)`, `skipped_files(...)`, `is_binary(...)`, `IGNORED_TOKEN` |
| `llm` | `analyze_changes(...)`, `http_chat(config)` |
| `output` | `build_report(...)`, `build_html(...)`, `build_json(...)` |
| `common` | `warn(message)` |

Everything else is an underscore-prefixed internal. Notably, all of git's path
quoting, prefix and separator handling lives inside `gitdiff` — callers only ever
see plain relative paths.

Dependencies run one way: `common` imports nothing from the package, `gitdiff` and
`rules` depend only on it, `compare` builds on those, and `cli` wires everything
together. There are no import cycles.

### The chat seam

`analyze_changes` does not build an HTTP client — it accepts one:

```python
chat(system, user, label) -> str | None
```

`http_chat(config)` is the real adapter, talking to the OpenAI-compatible endpoint
and returning `None` on any failure. Tests pass a fake, which is what lets the entire
analysis stage — file capping, hunk splitting, summary folding — be tested in-process
with no server running. If you ever need a second backend, this is where it plugs in.

## Requirements

| Component | Version | Required? | Note |
|---|---|---|---|
| Python | 3.8+ | yes | Standard library only — **no pip dependencies** |
| git | 2.30+ | yes | Needs `git diff --no-index` |
| clang-format | any | optional | Formatting normalization for C/C++ |
| gcc | any | optional | Powers `strip-comments` |

If `clang-format` or `gcc` is missing, the tool prints a warning to stderr and
continues without it. The report is still produced — but formatting and comment
changes will count as real changes, because nothing normalized them away.

## Installing on an air-gapped network

The tool is designed to be copied, not installed. No `pip install`, no virtualenv, no
packages to bring in from outside.

```bash
# 1. Copy the package directory and the config onto the closed network:
#    dirdiff/  (the whole directory)
#    config.json

# 2. Check the tool versions
python3 --version    # needs 3.8+
git --version        # needs 2.30+

# 3. Confirm the package is intact — this must print the usage text
python3 -m dirdiff --help

# 4. Optional — the normalizers
clang-format --version
gcc --version
```

`dirdiff/` must be copied whole; the modules import each other and a partial copy
fails at import time. Step 3 is the cheap way to catch that before you need the tool.

If `clang-format` is missing and a local RPM repository is available:

```bash
sudo yum install clang-tools-extra   # provides clang-format
sudo yum install gcc
```

If there is no repository, just remove `"clang-format"` and `"strip-comments"` from the
`normalize` list in the config and rely on `ignore_lines` alone.

## Usage

Run it as a module, from the directory holding `dirdiff/`:

```bash
python3 -m dirdiff DIR_A DIR_B -c config.json -o report.md
python3 -m dirdiff DIR_A DIR_B -c config.json -o report.md --no-llm
python3 -m dirdiff DIR_A DIR_B -c config.json -o report.md -H report.html
python3 -m dirdiff DIR_A DIR_B -c config.json -o report.md -j report.json
```

| Flag | Default | Meaning |
|---|---|---|
| `DIR_A` | — | First directory (the old version) |
| `DIR_B` | — | Second directory (the new version) |
| `-c`, `--config` | `config.json` | Config file |
| `-o`, `--output` | `report.md` | Report file to write |
| `-H`, `--html` | off | Also write a self-contained HTML report |
| `-j`, `--json` | off | Also write JSON output for automated consumers |
| `--no-llm` | off | Produce the report without model analysis |

## Config file

```json
{
  "llm": {
    "base_url": "http://localhost:8000/v1",
    "api_key": "",
    "model": "PLACEHOLDER-MODEL-NAME",
    "temperature": 0.2,
    "max_tokens": 1200,
    "max_chars_per_call": 24000,
    "max_files": 50,
    "timeout_sec": 180
  },
  "rules": [
    { "match": ["*.o", "*.log"], "skip": true },
    {
      "match": ["*.c", "*.h"],
      "normalize": ["strip-comments", "clang-format"],
      "ignore_lines": ["^\\s*#define\\s+BUILD_NUMBER\\b"]
    },
    { "match": ["*.json"], "normalize": ["json-sort"] }
  ]
}
```

### `llm` fields

| Field | Meaning |
|---|---|
| `base_url` | OpenAI-compatible server address (vLLM, for example). Empty or missing → analysis is skipped |
| `api_key` | Sent as `Authorization: Bearer`. May be left empty |
| `model` | Model name as the server knows it |
| `temperature`, `max_tokens` | Passed through to the request as-is |
| `max_chars_per_call` | A diff longer than this is split on `@@` boundaries and analyzed in parts |
| `max_files` | Cap on files analyzed. Beyond it, a warning is printed |
| `timeout_sec` | Timeout for each HTTP call |

### Rule fields

| Field | Type | Meaning |
|---|---|---|
| `match` | list of patterns | `fnmatch` patterns tested against the relative path **and** the basename |
| `skip` | boolean | The file is deleted from both copies — never compared |
| `normalize` | list of commands | Run in order, stdin to stdout, 60-second timeout |
| `ignore_lines` | list of regexes | Every matching line is replaced with a fixed token on both sides |

**First matching rule wins.** Rules are tested in list order, so put specific rules
before general ones.

#### Built-in normalizer aliases

| Alias | Actual command |
|---|---|
| `clang-format` | `clang-format -style=LLVM -assume-filename={name}` |
| `strip-comments` | `gcc -fpreprocessed -dD -E -P -x c -` |
| `json-sort` | Python: read JSON from stdin, write it back with `sort_keys=True` |

Any other string is run as a shell command as-is. The substring `{name}` is replaced
with the file's basename. If a command exits non-zero, a warning is printed and the
pre-normalization text is kept.

#### Why `ignore_lines` and not `git diff -I`

Git has an `-I` flag for ignoring lines by regex, but it is global: you cannot set one
regex for `.c` files and a different one for `.json` files in the same invocation.
Replacing those lines with a fixed token on both sides achieves per-file-type ignoring
within a single `git diff` call, and preserves the line count so diff line numbers do
not shift.

## Report structure

| Section | Content |
|---|---|
| Header | Both directories, date, and the counts: real / noise only / skipped |
| `## Executive summary` | Overall summary and risk level — only if model analysis ran |
| `## Files` | File and status for every changed file |
| `## Changes` | For each real change: the model's analysis, then the normalized diff inside `<details>` |

For each file the model is asked to return **Summary** (one sentence), **Changes**
(bullets) and **Risk** (Low/Medium/High with justification). Binary files are detected
by a NUL byte in the first 8KB, are not normalized, and get a one-line note instead of
a diff.

## HTML output — a report you can hand to a reviewer

The `-H` flag writes the same report as a single HTML file. It is meant for the
reviewer who is not reading Markdown in a terminal: counts as headline figures, a
file table where noise and skipped rows are visually recessed, a risk badge wherever
one could be extracted, and every change shown as a **side-by-side comparison**.

### The side-by-side view

Two panes, headed with the directory each belongs to, aligned row by row the way a
dedicated comparison tool shows them:

| Row | Meaning |
|---|---|
| Both sides filled, same text | Context — unchanged, with the line number each side has |
| Both sides filled, coloured | An edited line, old on the left and new on the right, with **the characters that actually differ marked** |
| One side blank | An insertion or a deletion; the blank half keeps the rows aligned |
| `⋯` | A gap between hunks — lines that were skipped |

Character-level marking is only applied when the two lines are actually related
(similarity of 0.5 or better). Below that they are unrelated, and marking every
differing character would light up the whole row instead of informing.

Both panes live in one table, so they cannot drift out of alignment, and the line
numbers on each side are independent — after an insertion the left pane keeps its
own numbering, which is what lets you see how far the two files have diverged.

Markdown and JSON keep the unified diff: side-by-side needs real columns, and the
JSON `diff` field stays the format an automated consumer already parses.

```bash
python3 -m dirdiff v1 v2 -c config.json -o report.md -H report.html
```

**The file is entirely self-contained** — styles are inlined and nothing is fetched
at render time. That is a hard requirement, not a preference: on a closed network a
report that reaches for a CDN renders unstyled. It also means the file can be copied
off the box, or opened straight from a `file://` path, with no server involved.

The page follows the reader's light or dark preference. There is no JavaScript in it;
the collapsible diffs are `<details>` elements.

Everything in the HTML comes from the same `Comparison` the Markdown is built from, so
the two never disagree. The risk badge is the regex-extracted level described below,
and it is simply absent when no level could be extracted — it is never guessed.

## JSON output — wiring into an automated pipeline

The `-j` flag writes a JSON file alongside the report, intended for an agent, a CI job,
or a review bot. The Markdown report is unchanged — the JSON is an addition, not a
replacement.

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-09T21:40:00",
  "dir_a": "src/v1",
  "dir_b": "src/v2",
  "llm_ran": true,
  "counts": { "real": 1, "noise": 2, "skipped": 1 },
  "summary": {
    "text": "full executive summary text...",
    "risk": "medium"
  },
  "real": [
    {
      "file": "sensor.c",
      "status": "M",
      "binary": false,
      "risk": "medium",
      "analysis": "full per-file analysis text...",
      "diff": "diff --git a/sensor.c b/sensor.c\n..."
    }
  ],
  "noise": ["limits.json", "util.h"],
  "skipped": ["build.log"]
}
```

| Field | Meaning |
|---|---|
| `schema_version` | Structure version. Bumped on a breaking change |
| `llm_ran` | Whether any analysis came back from the model |
| `counts` | The same counts shown in the report header |
| `real[].status` | Git status letter: `A` / `D` / `M` / `R` |
| `real[].analysis` | Full analysis text, or `null` if the model did not run or failed |
| `real[].diff` | The file's normalized diff section |
| `noise`, `skipped` | Filename lists only |

### About the risk field

The risk level comes back from the model as free-form prose, so it is **extracted with
a regular expression** from the `**Risk**` line (and, for the summary, the
`**Overall risk**` line). Values are `low`, `medium`, `high`, or `null`.

Extraction is best effort:

- `risk` is `null` whenever no level can be extracted — the model did not run, the call
  failed, or the answer was phrased differently. **An automated consumer must handle
  `null`** and must not assume a level is always present.
- A line naming all three levels is rejected, to guard against the model echoing the
  template back.
- When a diff was split into parts, the most severe level across the parts wins.

If you do not trust the extraction, ignore the risk field and parse `analysis`
yourself — the full text is always there.

## Tests

Unit tests covering the pure logic — rule matching, line ignoring, path handling,
diff splitting, risk extraction, and Markdown, HTML and JSON rendering (including
HTML escaping of diffs and filenames). No git, normalizers or network needed.

```bash
python3 -m unittest discover -s tests
```

## Known limitations

- **Diff line numbers refer to the normalized files**, not the originals. After
  `strip-comments` and `clang-format` the numbering shifts. Use the diff to understand
  the change, not to navigate the original file.
- **First matching rule wins, and there is no negation.** You cannot express "all `.c`
  files except `generated_*.c`". The workaround is to put a more specific rule first.
- **Files that are not valid UTF-8 are compared un-normalized.** Legacy sources with
  cp1252 comments or strings are left byte-for-byte, warned about on stderr, and
  compared as they are — so formatting and comment changes in them count as real
  changes. Normalizing them would mean decoding lossily, which can make two files
  that genuinely differ look identical, and a real change would vanish into "noise".
- A failed model call does not stop the run — a warning goes to stderr and the report is
  produced without that analysis.
- Skipped files are never compared, so the report cannot tell you **what** changed in
  them.
