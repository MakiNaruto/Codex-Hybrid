"""Platform-neutral desktop lifecycle boundary used by management.

Backends provide discover(home), processes(target), close(target, timeout), and
launch(target, timeout). Targets stay private to their backend. A missing backend
or installation returns None from discover so configuration changes can proceed
with manual desktop handling. No backend may force-terminate the application.
"""
from dataclasses import dataclass
from importlib import import_module
import sys


@dataclass(frozen=True)
class CloseResult:
    success: bool
    reason: str = ''

    def __bool__(self):
        return self.success


class DesktopControlError(OSError):
    pass


def backend():
    if sys.platform == 'win32':
        return import_module('desktop.windows_client')
    if sys.platform == 'darwin':
        # Add a native macOS backend here after installation identity, normal
        # app quit, permissions and launch behavior have been validated on Mac.
        return None
    return None


def discover(home):
    implementation = backend()
    return implementation.discover(home) if implementation is not None else None


def _required_backend():
    implementation = backend()
    if implementation is None:
        raise DesktopControlError('unsupported_platform')
    return implementation


def processes(target):
    return _required_backend().processes(target)


def close(target, timeout=12):
    return _required_backend().close(target, timeout=timeout)


def launch(target, timeout=20):
    return _required_backend().launch(target, timeout=timeout)
