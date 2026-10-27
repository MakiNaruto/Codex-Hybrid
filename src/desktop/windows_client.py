"""One-shot, graceful Windows desktop lifecycle. Never terminate backend processes."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import psutil
from desktop.client import CloseResult, DesktopControlError


def discover(home):
    # Store activation cannot reliably select an arbitrary CODEX_HOME.
    if sys.platform != 'win32' or Path(home).resolve() != (Path.home()/'.codex').resolve():
        return None
    script = """[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-AppxPackage -Name OpenAI.Codex* | ForEach-Object {
  $pkg = $_
  $manifest = Get-AppxPackageManifest -Package $pkg.PackageFullName
  $manifest.Package.Applications.Application | ForEach-Object {
    if ($_.Executable -and $_.Id) {
      [pscustomobject]@{executable=(Join-Path $pkg.InstallLocation $_.Executable); app_id=($pkg.PackageFamilyName + '!' + $_.Id)}
    }
  }
} | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
        entries = json.loads(result.stdout)
        entries = entries if isinstance(entries, list) else [entries]
        entries = [entry for entry in entries if Path(entry['executable']).is_file()]
        if len(entries) == 1:
            return entries[0]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    # Some restricted Windows sessions cannot enumerate Appx registration. A running
    # app's installed manifest supplies the same activation identity, without guessing.
    targets = {}
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() != 'chatgpt.exe':
            continue
        try:
            executable = Path(process.exe())
            package = executable.parent.parent
            if package.parent.name.lower() != 'windowsapps' or not package.name.lower().startswith('openai.codex_'):
                continue
            manifest = ET.parse(package/'AppxManifest.xml').getroot()
            namespace = {'app': 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
            identity = manifest.find('app:Identity', namespace)
            if identity is None or identity.get('Name') != 'OpenAI.Codex':
                continue
            for application in manifest.findall('app:Applications/app:Application', namespace):
                path = package/application.get('Executable', '')
                if path.resolve() != executable.resolve() or not application.get('Id'):
                    continue
                family = identity.get('Name') + '_' + package.name.rsplit('__', 1)[1]
                targets[str(executable)] = {'executable': str(executable),
                                            'app_id': family + '!' + application.get('Id')}
        except (OSError, ValueError, IndexError, ET.ParseError, psutil.Error):
            continue
    return next(iter(targets.values())) if len(targets) == 1 else None


def processes(target):
    """Exact installed executable identity, including Electron's main process only."""
    found = []
    expected = os.path.normcase(os.path.abspath(target['executable']))
    basename = Path(target['executable']).name.lower()
    for process in psutil.process_iter(['name']):
        try:
            if (process.info['name'] or '').lower() != basename:
                continue
            if os.path.normcase(os.path.abspath(process.exe())) != expected:
                continue
            if any(arg.startswith('--type=') for arg in process.cmdline()[1:]):
                continue
            found.append(process)
        except psutil.NoSuchProcess:
            continue
        # AccessDenied deliberately propagates: unknown is never treated as stopped.
    return found


def _user32():
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    return user32


def _windows(pids):
    """Visible Electron application windows, excluding hidden message/tray helpers."""
    user32 = _user32()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows = []

    @callback_type
    def visit(window, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(window):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(window, name, len(name))
            if name.value.startswith('Chrome_WidgetWin_') and user32.GetWindowTextLengthW(window):
                windows.append(window)
        return True

    if not user32.EnumWindows(visit, 0):
        raise DesktopControlError('window_enumeration_failed')
    return windows


def _current_thread_id():
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    return kernel32.GetCurrentThreadId()


def _focus_window(user32, window):
    if user32.GetForegroundWindow() == window:
        return True
    user32.SetForegroundWindow(window)
    if user32.GetForegroundWindow() == window:
        return True
    # A background gateway does not own the foreground input queue. Temporarily
    # attach it for this one user-requested operation, then always detach it.
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    current = _current_thread_id()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    if not foreground_thread or foreground_thread == current:
        return False
    if not user32.AttachThreadInput(current, foreground_thread, True):
        return False
    try:
        user32.SetForegroundWindow(window)
        deadline = time.monotonic() + 1
        while user32.GetForegroundWindow() != window:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True
    finally:
        user32.AttachThreadInput(current, foreground_thread, False)


def _send_quit_shortcut(user32, window):
    # Input is allowed only while the exact target window owns the foreground.
    # Never inject into another app, or interfere with physically held modifiers.
    if user32.GetForegroundWindow() != window:
        return CloseResult(False, 'foreground_denied')
    if any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C, 0x51)):
        return CloseResult(False, 'modifier_held')

    class MouseInput(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('data', wintypes.DWORD),
                    ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', wintypes.WPARAM)]

    class KeyboardInput(ctypes.Structure):
        _fields_ = [('key', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('extra', wintypes.WPARAM)]

    class HardwareInput(ctypes.Structure):
        _fields_ = [('message', wintypes.DWORD), ('low', wintypes.WORD), ('high', wintypes.WORD)]

    class InputValue(ctypes.Union):
        _fields_ = [('mouse', MouseInput), ('keyboard', KeyboardInput), ('hardware', HardwareInput)]

    class Input(ctypes.Structure):
        _fields_ = [('kind', wintypes.DWORD), ('value', InputValue)]

    sequence = (Input * 4)()
    for item, (key, flags) in zip(sequence, ((0x11, 0), (0x51, 0), (0x51, 2), (0x11, 2))):
        item.kind = 1  # INPUT_KEYBOARD; KEYEVENTF_KEYUP = 2.
        item.value.keyboard = KeyboardInput(key, 0, flags, 0, 0)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    if user32.GetForegroundWindow() != window:
        return CloseResult(False, 'foreground_changed')
    sent = user32.SendInput(len(sequence), sequence, ctypes.sizeof(Input))
    if 0 < sent < len(sequence):
        # A partial insertion must not leave Ctrl/Q logically held down. Only
        # release keys; do not retry the application quit command.
        releases = (Input * 2)(sequence[2], sequence[3])
        user32.SendInput(len(releases), releases, ctypes.sizeof(Input))
    return CloseResult(sent == len(sequence), '' if sent == len(sequence) else 'input_blocked')


def _request_quit(roots):
    windows = _windows({process.pid for process in roots})
    if not windows:
        return CloseResult(False, 'no_visible_window')
    user32 = _user32()
    foreground = user32.GetForegroundWindow()
    window = foreground if foreground in windows else windows[0]
    if user32.IsIconic(window):
        user32.ShowWindowAsync(window, 9)  # SW_RESTORE.
    if not _focus_window(user32, window):
        return CloseResult(False, 'foreground_denied')
    # Codex's native Windows application menu binds Ctrl+Q to app.quit().
    # WM_CLOSE only closes a window and may leave the application in the tray.
    return _send_quit_shortcut(user32, window)


def close(target, timeout=12):
    roots = processes(target)
    if not roots:
        return True
    request = _request_quit(roots)
    if not request:
        return request
    _, alive = psutil.wait_procs(roots, timeout=timeout)
    if alive:
        return CloseResult(False, 'exit_timeout')
    if processes(target):
        return CloseResult(False, 'process_reappeared')
    return CloseResult(True)


def launch(target, timeout=20):
    # A remaining background process is not a visible application. Always send
    # the single requested activation and wait for an actual desktop window.
    subprocess.Popen(['explorer.exe', 'shell:AppsFolder\\' + target['app_id']],
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _windows({process.pid for process in processes(target)}):
            return 'started'
        time.sleep(0.4)
    return 'launch_unconfirmed'
