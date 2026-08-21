"""Pytest path setup.

phage.marrow.agent imports agents.* (the real target agents) to fire
payloads at them; agents/ is a repo-root sibling of src/, not part of the
installed phage package, so the repo root must be on sys.path before that
import happens — the exact same requirement scripts/run_marrow.py documents
and satisfies for its own entry-point use. Test collection is another entry
point with the same requirement, so it gets the same fix, not a new one.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
