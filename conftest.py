"""pytest configuration.

Ensures the repository root is importable so tests can `import utils...`
regardless of where pytest is invoked from.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
