#!/usr/bin/env python3
"""Entrypoint script for update-ip monitor."""

import sys
from pathlib import Path

# Add src directory to sys.path
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from update_ip.cli import main

if __name__ == "__main__":
    main()
