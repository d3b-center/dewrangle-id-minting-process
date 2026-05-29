"""Entry point shim for d3b-dewrangle CLI."""
import sys
from pathlib import Path

# Ensure d3b-dewrangle-cli is on sys.path so 'scripts' and 'src' are importable
_CLI_DIR = Path(__file__).resolve().parent
_cli_dir_str = str(_CLI_DIR)
if _cli_dir_str in sys.path:
    sys.path.remove(_cli_dir_str)
sys.path.insert(0, _cli_dir_str)

from scripts.d3b_dewrangle import main

if __name__ == "__main__":
    main()
