"""Console entry point for the shared gold-loot tracker."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.gold_loot import connect, gold, leaderboard, main, save_sample

if __name__ == '__main__':
    sys.exit(main())
