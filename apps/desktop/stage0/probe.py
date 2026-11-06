"""Compatibility entry point. Desktop commands are implemented in sidecar/main.py."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'sidecar/main.py'), run_name='__main__')
