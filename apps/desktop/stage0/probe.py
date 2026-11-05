"""Isolated feasibility probe, not the production desktop control protocol.

Control/gateway modes require an explicit fixture settings file. The separate
desktop-snapshot mode reads the fixed desktop directory without modifying it.
"""
import argparse
import io
import json
from pathlib import Path
import sys
import threading

from gateway.server import Gateway, Server
from management.http import WEB


def report():
    import psutil
    import yaml
    return {
        'frozen': bool(getattr(sys, 'frozen', False)),
        'python': sys.version.split()[0],
        'utf8_mode': sys.flags.utf8_mode,
        'yaml': yaml.__version__,
        'psutil': psutil.__version__,
        'static_files': {name: (WEB / name).is_file()
                         for name in ('index.html', 'app.js', 'entry.html', 'entry.js', 'style.css')},
    }


class FixtureOpener:
    """No network: exercise real request construction and stream adaptation."""
    def open(self, request, timeout):
        if request.full_url != 'https://stage0.invalid/v1/responses':
            raise ValueError('UNEXPECTED_FIXTURE_ENDPOINT')
        if json.loads(request.data)['model'] != 'fixture-model':
            r