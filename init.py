#!/usr/bin/env python3
"""
Quickstart initialization script for Antigravity Bridge.
Run this directly from the cloned repository root:
    python init.py
"""

import sys
import os

# Ensure package is on sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from antigravity_bridge.cli import init_cmd

if __name__ == "__main__":
    init_cmd()
