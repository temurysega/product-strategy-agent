"""Portable stdio entry point independent of the editor's working directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategy_agent.mcp import main

if __name__ == "__main__":
    main()
