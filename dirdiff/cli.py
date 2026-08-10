"""Command-line entry point.

Public interface:
    main(argv=None) -> exit code

This module is wiring only: read arguments and config, choose the chat adapter,
run the pipeline, write the files. All the behaviour lives behind the interfaces
it calls.
"""

import argparse
import json
import os
import sys

from .common import warn
from .compare import compare
from .llm import analyze_changes, http_chat
from .output import build_html, build_json, build_report


def main(argv=None):
    _configure_streams()
    args = _parse_args(argv)
    dir_a = args.dir_a.rstrip("/\\")
    dir_b = args.dir_b.rstrip("/\\")

    for path in (dir_a, dir_b):
        if not os.path.isdir(path):
            sys.stderr.write("Error: '%s' is not an existing directory.\n" % path)
            return 2
    try:
        with open(args.config, "r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: cannot read config file '%s': %s\n" % (args.config, exc))
        return 2

    llm = config.get("llm") or {}
    comparison = compare(dir_a, dir_b, config.get("rules") or [])

    analyses, summary = {}, None
    if args.no_llm:
        pass
    elif not llm.get("base_url"):
        warn("llm.base_url is not set in the config — producing the report without LLM analysis.")
    else:
        analyses, summary = analyze_changes(
            comparison,
            http_chat(llm),
            max_files=llm.get("max_files", 50),
            max_chars=llm.get("max_chars_per_call", 24000),
        )

    report = build_report(dir_a, dir_b, comparison, analyses, summary)
    if not _write(args.output, report, "report"):
        return 2

    if args.html:
        page = build_html(dir_a, dir_b, comparison, analyses, summary)
        if not _write(args.html, page, "HTML report"):
            return 2

    if args.json:
        payload = build_json(dir_a, dir_b, comparison, analyses, summary)
        if not _write(args.json, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "JSON file"):
            return 2

    print(
        "Report written to %s — %d real changes, %d noise only, %d skipped."
        % (args.output, len(comparison.real), len(comparison.noise), len(comparison.skipped))
    )
    return 0


# --- internals ---------------------------------------------------------------


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="dirdiff",
        description="dirdiff — rule-based directory comparison, with LLM analysis of "
        "the real changes only.",
    )
    parser.add_argument("dir_a", metavar="DIR_A", help="first directory (the old version)")
    parser.add_argument("dir_b", metavar="DIR_B", help="second directory (the new version)")
    parser.add_argument(
        "-c", "--config", default="config.json", help="JSON config file (default: config.json)"
    )
    parser.add_argument(
        "-o", "--output", default="report.md", help="report file to write (default: report.md)"
    )
    parser.add_argument(
        "-H",
        "--html",
        metavar="PATH",
        help="also write a self-contained HTML report; off unless given",
    )
    parser.add_argument(
        "-j",
        "--json",
        metavar="PATH",
        help="also write JSON output for automated consumers (agent, CI); off unless given",
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="skip LLM analysis and produce a diff-only report"
    )
    return parser.parse_args(argv)


def _configure_streams():
    """Force UTF-8 on stdout/stderr so output is identical across platforms."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _write(path, text, what):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return True
    except OSError as exc:
        sys.stderr.write("Error: cannot write %s '%s': %s\n" % (what, path, exc))
        return False
