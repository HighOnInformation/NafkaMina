"""What this change defined and what it took away — computed, not guessed.

Public interface:
    cross_reference(sections, dir_b) -> CrossReference
    CrossReference                       namedtuple(removed, dangling)

`removed` is {path: [symbol]} for definitions this change deleted. `dangling` is
{symbol: [path]} for those the new tree still references — the reviewer's actual
question ("is legacy_calibrate still called?") answered without a model.

Deliberately conservative. Only two definition forms are recognised, and a
definition must carry a body, because in a review tool a heuristic that
over-reports is worse than one that under-reports: a false "still referenced"
costs an investigation, a missed one costs nothing that was not already missed.
Nothing here is a substitute for a compiler.

Depends on `common` and `rules` only, so the one-way import chain still holds.
"""

import collections
import os
import re

from .rules import is_binary

CrossReference = collections.namedtuple("CrossReference", "removed dangling")

_DEFINE_RE = re.compile(r"^#\s*define\s+([A-Za-z_]\w*)")

# Words that can stand where a return type would, and would otherwise make a
# control-flow line look like a function definition.
_NOT_A_TYPE = frozenset(
    """if else for while switch do return goto case default sizeof typedef
    break continue""".split()
)


def cross_reference(sections, dir_b):
    """Find definitions this change removed, and which of them are still used."""
    added, removed_by_file = set(), {}
    for rel, section in sections.items():
        gained, lost = _definitions(section)
        added |= gained
        if lost:
            removed_by_file[rel] = lost

    # A symbol removed from one file and defined in another moved; it is still
    # defined, so it is neither a removal nor dangling.
    removed_by_file = {
        rel: sorted(names - added) for rel, names in removed_by_file.items()
    }
    removed_by_file = {rel: names for rel, names in removed_by_file.items() if names}

    gone = {name for names in removed_by_file.values() for name in names}
    return CrossReference(
        removed=removed_by_file,
        dangling=_references(dir_b, gone) if gone else {},
    )


# --- internals ---------------------------------------------------------------


def _definitions(section):
    """Return (added, removed) symbol names from one diff section."""
    added, removed = set(), set()
    for line in section.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            target, text = added, line[1:]
        elif line.startswith("-") and not line.startswith("---"):
            target, text = removed, line[1:]
        else:
            continue
        name = _defined_name(text.strip())
        if name:
            target.add(name)
    return added, removed


def _defined_name(text):
    """The symbol a line defines, or None.

    A function definition must end in '{': without a body it is a declaration,
    and a prototype moving between headers is not a change in what exists. It
    must also carry a return type, which is what separates 'int foo(void){' from
    'if(cond){' — the latter has nothing before the parenthesis.
    """
    match = _DEFINE_RE.match(text)
    if match:
        return match.group(1)
    if not text.endswith("{") or "(" not in text:
        return None
    tokens = text.split("(", 1)[0].replace("*", " ").split()
    if len(tokens) < 2:
        return None
    name = tokens[-1]
    if name in _NOT_A_TYPE or tokens[0] in _NOT_A_TYPE:
        return None
    return name if re.match(r"^[A-Za-z_]\w*$", name) else None


def _references(dir_b, names):
    """Which files in the new tree still mention each of these names.

    Decoding is lossy on purpose here, unlike normalization: this only looks for
    ASCII identifiers, so a byte that will not decode cannot hide a match, and
    refusing to read the file would.
    """
    pattern = re.compile(r"\b(%s)\b" % "|".join(re.escape(n) for n in sorted(names)))
    found = {}
    for root, _dirs, files in os.walk(dir_b):
        for name in files:
            path = os.path.join(root, name)
            if is_binary(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            rel = os.path.relpath(path, dir_b).replace("\\", "/")
            for symbol in set(pattern.findall(text)):
                found.setdefault(symbol, []).append(rel)
    return {symbol: sorted(paths) for symbol, paths in sorted(found.items())}
