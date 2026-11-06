"""Shared service CLI argument contract."""
import argparse
import os
from pathlib import Path


ACTIONS = ('prepare', 'refresh-models', 'start', 'restart', 'stop', 'status',
           'activate', 'rollback', 'uninstall', 'manage-url', 'recover-sessions', 'reset-session-baseline')


def common_arguments(parser, defaults):
    # Subcommands suppress unset values so options placed before the action survive.
    value = (lambda item: item) if defaults else (lambda item: argparse.SUPPRESS)
    parser.add_argument('--data-dir', type=Path, default=value(None),
                        help='Private data directory (or CODEX_HYBRID_DATA_DIR)')
    parser.add_argument('--port', type=int, default=value(18891))
    parser.add_argument('--codex-home', type=Path,
                        default=value(Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))))
    parser.add_argument('--source', choices=['yaml', 'cc-switch'], default=value(None))
    parser.add_argument('--models-config', type=Path, default=value(None))
    parser.add_argument('--cc-db', type=Path, default=value(Path.home() / '.cc-switch/cc-switch.db'))


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common_arguments(common, defaults=False)
    parser = argparse.ArgumentParser(description='Prepare, start, activate and roll back Codex Hybrid.', epilog='View instance settings: config [--data-dir PATH]')
    common_arguments(parser, defaults=True)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ACTIONS:
        command = commands.add_parser(action, parents=[common])
        if action == 'recover-sessions':
            command.add_argument('--backup', type=Path, required=True)
        if action == 'manage-url':
            command.add_argument('--management-auth', choices=['on', 'off'],
                help='Set management-link authentication on or off')
    return parser
