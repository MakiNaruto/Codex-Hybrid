"""Graceful macOS Codex lifecycle using Launch Services and Apple events."""
from pathlib import Path
import plistlib
import subprocess
import sys
import time

import psutil
from desktop.client import CloseResult


BUNDLE_ID = 'com.openai.codex'


def discover(home):
    if sys.platform != 'darwin' or Path(home).resolve() != (Path.home()/'.codex').resolve():
        return None
    candidates = [Path('/Applications/Codex.app'), Path.home()/'Applications/Codex.app']
    try:
        result = subprocess.run(['/usr/bin/mdfind', f'kMDItemCFBundleIdentifier == "{BUNDLE_ID}"'],
                                capture_output=True, text=True, timeout=5, check=True)
        candidates.extend(Path(line) for line in result.stdout.splitlines() if line)
    except (OSError, subprocess.SubprocessError):
        pass
    for bundle in dict.fromkeys(path.resolve() for path in candidates):
        try:
            with (bundle/'Contents/Info.plist').open('rb') as source:
                info = plistlib.load(source)
            name = info.get('CFBundleExecutable', '')
            if info.get('CFBundleIdentifier') != BUNDLE_ID or not name or Path(name).name != name:
                continue
            executable = bundle/'Contents/MacOS'/name
            if executable.is_file():
                return {'bundle': str(bundle), 'executable': str(executable.resolve())}
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    return None


def processes(target):
    found = []
    expected = Path(target['executable']).resolve()
    for process in psutil.process_iter(['name']):
        try:
            if process.info.get('name') != expected.name:
                continue
            if Path(process.exe()).resolve() != expected:
                continue
            if any(arg.startswith('--type=') for arg in process.cmdline()[1:]):
                continue
            found.append(process)
        except psutil.NoSuchProcess:
            continue
    return found


def close(target, timeout=12):
    roots = processes(target)
    if not roots:
        return CloseResult(True)
    # Pass the verified bundle path as argv, never interpolate it into AppleScript.
    script = 'on run argv\ntell application (item 1 of argv) to quit\nend run'
    try:
        subprocess.run(['/usr/bin/osascript', '-e', script, target['bundle']],
                       capture_output=True, text=True, timeout=timeout, check=True)
    except subprocess.TimeoutExpired:
        return CloseResult(False, 'exit_timeout')
    except (OSError, subprocess.CalledProcessError):
        return CloseResult(False, 'quit_denied')
    _, alive = psutil.wait_procs(roots, timeout=timeout)
    if alive:
        return CloseResult(False, 'exit_timeout')
    if processes(target):
        return CloseResult(False, 'process_reappeared')
    return CloseResult(True)


def launch(target, timeout=20):
    subprocess.run(['/usr/bin/open', '-a', target['bundle']],
                   capture_output=True, timeout=timeout, check=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if processes(target):
            return 'started'
        time.sleep(0.4)
    return 'launch_unconfirmed'
