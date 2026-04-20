"""Root conftest.py — adds the repo root to sys.path so that 'shared' is importable as a package."""
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `from shared.message_envelope import ...` works.
repo_root = Path(__file__).parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
