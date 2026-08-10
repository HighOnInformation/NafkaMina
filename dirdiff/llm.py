"""Model analysis of the real changes.

Public interface:
    http_chat(llm_config) -> chat
    analyze_changes(comparison, chat, max_files, max_chars) -> (analyses, summary)

The seam is `chat`, a callable:

    chat(system, user, label) -> str | None

`analyze_changes` never builds a transport of its own — it is handed one. That is
what lets the whole analysis stage (file capping, hunk splitting, summary folding)
be tested in-process with a fake, without an HTTP server. `http_chat` is the real
adapter; a test fake is the second one, which is what makes this a seam worth having.

A chat callable returns None on failure rather than raising, so a dead endpoint
degrades the report instead of killing the run.
"""

import json
import urllib.request

from .common import warn

_SYSTEM_FILE = """You are a senior software engineer reviewing a code change.

The diff below has already been filtered automatically: comments, formatting,
whitespace and generated lines (timestamps, build numbers) were removed from it.
Every change that remains is therefore substantive — do not describe it as
stylistic.

Answer in English, using exactly this structure:

**Summary** — one sentence.

**Changes**
- one bullet per substantive change.

**Risk** — Low, Medium or High, followed by a short justification."""

_SYSTEM_SUMMARY = """You are the lead code reviewer. Below are analyses of individual
changed files, already filtered of formatting noise. Write an executive summary:
what actually changed, the practical implications, and what deserves attention
during review. End with a separate line in this exact format:

**Overall risk** — Low, Medium or High, followed by a short justification.

Be concise and do not repeat detail that already appears in the analyses."""


def http_chat(llm):
    """Build a chat callable that talks to an OpenAI-compatible endpoint."""

    def chat(system, user, label):
        try:
            return _post(llm, system, user)
        except Exception as exc:  # a model failure must never bring down the report
            warn("LLM analysis failed for %s: %s" % (label, exc))
            return None

    return chat


def analyze_changes(comparison, chat, max_files=50, max_chars=24000):
    """Analyze every real change, then fold the results into one summary.

    Returns (analyses, summary): a {path: text} mapping and the executive summary,
    either of which may be empty or None if the model produced nothing.
    """
    targets = [rel for rel in sorted(comparison.real) if rel not in comparison.binaries]
    if len(targets) > max_files:
        warn(
            "%d files to analyze but the limit is %d — the last %d will not be analyzed."
            % (len(targets), max_files, len(targets) - max_files)
        )
        targets = targets[:max_files]

    analyses = {}
    for rel in targets:
        section = comparison.sections.get(rel)
        if not section:
            continue
        answer = _analyze_file(chat, rel, section, max_chars)
        if answer:
            analyses[rel] = answer

    summary = _summarize(chat, sorted(analyses.items()), max_chars) if analyses else None
    return analyses, summary


# --- internals ---------------------------------------------------------------


def _post(llm, system, user):
    """Send one chat completion request and return the assistant's text."""
    url = llm.get("base_url", "").rstrip("/") + "/chat/completions"
    payload = {
        "model": llm.get("model", ""),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": llm.get("temperature", 0.2),
        "max_tokens": llm.get("max_tokens", 1200),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    if llm.get("api_key"):
        request.add_header("Authorization", "Bearer " + llm["api_key"])
    with urllib.request.urlopen(request, timeout=llm.get("timeout_sec", 180)) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    return data["choices"][0]["message"]["content"].strip()


def _analyze_file(chat, rel, section, max_chars):
    """Analyze one file's diff, splitting it across calls when it is too long."""
    if len(section) <= max_chars:
        return chat(_SYSTEM_FILE, "File: %s\n\n```diff\n%s```" % (rel, section), rel)

    parts = _split_by_hunks(section, max_chars)
    pieces = []
    for number, part in enumerate(parts, 1):
        answer = chat(
            _SYSTEM_FILE,
            "File: %s\nThis is part %d of %d of the diff.\n\n```diff\n%s```"
            % (rel, number, len(parts), part),
            "%s (part %d/%d)" % (rel, number, len(parts)),
        )
        if answer:
            pieces.append("#### Part %d of %d\n\n%s" % (number, len(parts), answer))
    return "\n\n".join(pieces) if pieces else None


def _summarize(chat, analyses, max_chars):
    """Fold all per-file analyses into one reviewer-level summary."""
    body = "\n\n".join("## %s\n%s" % (rel, text) for rel, text in analyses)
    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n[analyses truncated due to length limit]"
    return chat(_SYSTEM_SUMMARY, body, "executive summary")


def _split_by_hunks(section, limit):
    """Split a large diff section on @@ boundaries, repeating the file header."""
    lines = section.split("\n")
    index = 0
    while index < len(lines) and not lines[index].startswith("@@"):
        index += 1
    header = "\n".join(lines[:index])
    hunks = []
    current = []
    for line in lines[index:]:
        if line.startswith("@@") and current:
            hunks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        hunks.append("\n".join(current))
    if not hunks:
        return [section]

    parts = []
    batch = []
    size = len(header)
    for hunk in hunks:
        if batch and size + len(hunk) > limit:
            parts.append(header + "\n" + "\n".join(batch))
            batch = []
            size = len(header)
        batch.append(hunk)
        size += len(hunk)
    if batch:
        parts.append(header + "\n" + "\n".join(batch))
    return parts
