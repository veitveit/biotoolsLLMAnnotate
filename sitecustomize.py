"""Development convenience: make `src/` importable when running from repo root.

Python automatically imports `sitecustomize` if present on sys.path. This file
adds the `src/` directory to `sys.path` to allow `python -m biotoolsllmannotate`
to work without installing the package during development and testing.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(__file__)
_SRC = os.path.join(_ROOT, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)
