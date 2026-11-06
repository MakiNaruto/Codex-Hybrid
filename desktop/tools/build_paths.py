"""Shared desktop source and compatibility cache paths."""
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
ROOT = DESKTOP.parent
if not (ROOT / 'pyproject.toml').is_file() or not (ROOT / 'src/management/web').is_dir():
    raise RuntimeError('Desktop tools must belong to a Codex Hybrid checkout')
TAURI = DESKTOP / 'src-tauri'
SIDECAR = DESKTOP / 'sidecar/main.py'
WEB = ROOT / 'src/management/web'
# Reuse existing native caches and output consumers during the directory migration.
BUILD = DESKTOP / 'build/stage0'
DIST = DESKTOP / 'dist/stage0'
