"""Readability fixture with the live-sized empty-clan capacity case."""
import os
import runpy
from pathlib import Path

os.environ["WU_CAPACITY_HOTFIX"] = "1"
runpy.run_path(str(Path(__file__).with_name("roster_readability.py")), run_name="__main__")
