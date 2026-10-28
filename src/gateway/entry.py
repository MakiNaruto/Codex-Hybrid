"""Checkout gateway entry point; its path also identifies the owned process."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.server import main

if __name__ == '__main__':
    main()
