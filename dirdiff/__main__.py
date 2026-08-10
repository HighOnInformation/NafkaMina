"""Entry point so the package can be run as `python3 -m dirdiff`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
