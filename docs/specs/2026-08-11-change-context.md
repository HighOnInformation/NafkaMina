# Whole-change understanding, and externalized inputs

Design agreed 2026-08-11. Four parts, built in this order.

## The problem

Two structural gaps, not prompt weaknesses.

**The model never sees the change as a whole.** Each per-file call is blind to
every other file, and the summary folds per-file *prose* — it never sees a single
diff. So the pipeline cannot notice that `sensor.c` now calls something `util.h`
deleted. No prompt can fix that; the data never reaches the model.

**Every word sent to the model is compiled into the package.** The two system
prompts, the three user-message templates, the normalizer command lines and the
risk labels are all Python constants. On a closed network they cannot be
reviewed, approved or tuned without editing source.

## Part A — deterministic cross-reference (no model)

A new `dirdiff/symbols.py`:

    cross_reference(sections, dir_b) -> CrossReference
    CrossReference  namedtuple(removed, dangling)

`removed` maps a path to the definitions this change deleted. `dangling` maps a
deleted symbol to the files in the new tree that still reference it.

Deliberately conservative. Two definition forms only — a function definition and
`#define NAME` — because a heuristic that over-reports is worse than one that
under-reports in a review tool. A symbol removed in one file and added in another
is a move, not a removal, and is excluded.

This is the only part that works with `--no-llm`, and it answers the question the
product review identified as the reviewer's real one: *is `legacy_calibrate`
still referenced?* It is also the factual input the later passes reason over,
rather than guessing.

Rendered in all three output formats, and passed to the builders as an optional
keyword argument so existing signatures keep working.

## Part B — orientation pass (pass 0)

Build a change manifest deterministically: file, status, churn, symbols added and
removed, plus the Part A findings. Send the manifest — **not** the diffs — and
ask what the change appears to be and which files look coupled. A few hundred
tokens for a whole drop.

Inject that brief into every per-file prompt, so each file is read in context
instead of in a vacuum. Same call count as today; the highest value per token
of anything here.

## Part C — externalized inputs

Optional `prompts`, `risk`, `normalizers` and `tuning` sections in the config,
with an `@path` prefix meaning "read this file", so prose stays reviewable
Markdown rather than JSON escapes. Named placeholders (`{path}`, `{diff}`,
`{part}`), validated at load — an unknown placeholder is a startup error.

**The risk labels move with the prompts.** `_extract_risk` looks for the literal
label the prompt asks for; translating the prompt without moving the label makes
every badge silently vanish. They are one coupled input.

Everything defaults to today's built-ins, so existing configs keep working. A new
`dirdiff/settings.py` loads, validates and resolves, so the rest of the package
still receives plain values and `config.get(...)` does not leak across modules.

Record `prompts_sha256` in the JSON so a report is traceable to the prompt set
that produced it.

## Part D — reconciliation pass (pass 2)

Give today's summary call the manifest *and* the per-file analyses, and ask for
two further things: which findings connect across files, and which per-file
conclusions should be revised now that the whole is visible. Revisions render
next to the affected file, not only at the top.

Cost across B and D: N+2 calls instead of N+1 — one extra call regardless of
drop size.

## Order and rationale

A, then B, then C, then D. A is the only part that improves the tool with the
model switched off. C is easier once B and D have settled the final prompt shape,
rather than freezing today's.
