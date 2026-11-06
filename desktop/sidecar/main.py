"""Frozen desktop entry point and compatibility dispatch for isolated validation."""
import argparse
import json
from pathlib import Path
import sys

# Source entry points can run outside the repository working directory.
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('report', 'control', 'gateway', 'desktop-snapshot', 'desktop-manage', 'desktop-controller'))
    parser.add_argument('--settings', type=Path)
    args = parser.parse_args()
    if args.mode == 'desktop-controller':
        from codex_integration.controller import main as controller
        controller()
        return
    if args.mode == 'desktop-manage':
        from codex_integration.management import main as manage
        manage()
        return
    if args.mode == 'desktop-snapshot':
        from codex_integration.snapshot import snapshot
        print(json.dumps(snapshot(), ensure_ascii=False))
        return
    from validation.probe import report, run
    if args.mode == 'report':
        print(json.dumps(report()))
        return
    run(args, parser)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
