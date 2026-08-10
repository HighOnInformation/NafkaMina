"""Non-fatal problem reporting.

Public interface:
    warn(message)

Deliberately one function. It exists so the "Warning: " convention and the choice
of stream live in one place rather than in every module that reports a problem.
"""

import sys


def warn(message):
    """Report a non-fatal problem. The run always continues past these."""
    sys.stderr.write("Warning: %s\n" % message)
