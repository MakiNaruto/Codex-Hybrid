"""Cooperative background shutdown of exact Windows process identities.

Register process resources only (never files/services), verify the affected list,
and call RmShutdown with flags=0. RmForceShutdown is deliberately never enabled.
"""
import ctypes
from ctypes import wintypes
import os

from desktop.client import CloseResult, DesktopControlError


class UniqueProcess(ctypes.Structure):
    _fields_ = [('pid', wintypes.DWORD), ('started', wintypes.FILETIME)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('process', UniqueProcess), ('name', wintypes.WCHAR * 256),
                ('service', wintypes.WCHAR * 64), ('application_type', ctypes.c_int),
                ('status', wintypes.ULONG), ('session', wintypes.DWORD), ('restartable', wintypes.BOOL)]


def _identity(process):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    expected = os.path.normcase(os.path.abspath(process.exe()))
    handle = kernel.OpenProcess(0x1000, False, process.pid)  # PROCESS_QUERY_LIMITED_INFORMATION.
    if not handle:
        raise DesktopControlError('restart_manager_identity_failed')
    try:
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            raise DesktopControlError('restart_manager_identity_failed')
        if not process.is_running() or os.path.normcase(os.path.abspath(path.value)) != expected:
            raise DesktopControlError('restart_manager_identity_changed')
        started, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(started), ctypes.byref(exited),
                                      ctypes.byref(system), ctypes.byref(user)):
            raise DesktopControlError('restart_manager_identity_failed')
        return UniqueProcess(process.pid, started)
    finally:
        kernel.CloseHandle(handle)


def _api():
    api = ctypes.WinDLL('rstrtmgr', use_last_error=True)
    api.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
    api.RmRegisterResources.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.c_void_p,
                                      wintypes.UINT, ctypes.POINTER(UniqueProcess), wintypes.UINT, ctypes.c_void_p]
    api.RmGetList.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
                            ctypes.POINTER(ProcessInfo), ctypes.POINTER(wintypes.DWORD)]
    api.RmShutdown.argtypes = [wintypes.DWORD, wintypes.ULONG, ctypes.c_void_p]
    api.RmEndSession.argtypes = [wintypes.DWORD]
    for name in ('RmStartSession', 'RmRegisterResources', 'RmGetList', 'RmShutdown', 'RmEndSession'):
        getattr(api, name).restype = wintypes.DWORD
    return api


def _key(process):
    return process.pid, process.started.dwHighDateTime, process.started.dwLowDateTime


def _scope_matches(api, session, identities):
    needed, count, reboot = wintypes.UINT(), wintypes.UINT(), wintypes.DWORD()
    result = api.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reboot))
    for _ in range(3):
        if result == 0 and needed.value == 0:
            return not reboot.value
        if result != 234 or needed.value > len(identities):  # ERROR_MORE_DATA.
            return False
        count.value = needed.value
        entries = (ProcessInfo * count.value)()
        result = api.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), entries, ctypes.byref(reboot))
        if result == 0:
            expected = {_key(identity) for identity in identities}
            return not reboot.value and all(_key(entry.process) in expected
                                           and entry.application_type in (1, 2)  # GUI windows only.
                                           for entry in entries[:count.value])
    return False


def shutdown(processes):
    identities = (UniqueProcess * len(processes))(*(_identity(process) for process in processes))
    if not identities:
        return CloseResult(True)
    api, session = _api(), wintypes.DWORD()
    if api.RmStartSession(ctypes.byref(session), 0, ctypes.create_unicode_buffer(33)):
        return CloseResult(False, 'restart_manager_start_failed')
    try:
        if api.RmRegisterResources(session, 0, None, len(identities), identities, 0, None):
            return CloseResult(False, 'restart_manager_registration_failed')
        if not _scope_matches(api, session, identities):
            return CloseResult(False, 'restart_manager_scope_changed')
        # Zero flags: respect cooperative shutdown refusal, never force termination.
        result = api.RmShutdown(session, 0, None)
        return CloseResult(result == 0, '' if result == 0 else 'restart_manager_shutdown_failed')
    finally:
        api.RmEndSession(session)
