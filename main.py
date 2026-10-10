"""
Root entry point for the Intraday Alert Bot.
Delegates to engine.__main__.main().
Usage:
    python main.py doctor
    python main.py run
    python main.py replay --date YYYY-MM-DD
    python main.py notify-test
    python main.py publish-test
    python main.py universe
    python main.py collect-eod
    python main.py filings
"""
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from engine.__main__ import main

if __name__ == "__main__":
    main()
