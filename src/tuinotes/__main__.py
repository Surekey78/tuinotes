"""Allow `python -m tuinotes`."""

from __future__ import annotations

import sys

from tuinotes.cli import main

if __name__ == "__main__":
    sys.exit(main())
