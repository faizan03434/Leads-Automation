"""Persist SMTP credentials using Windows DPAPI for the current Windows user."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

STORE = Path(__file__).parent / 'mailbox.dpapi'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(raw, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Saved mailbox credentials require Windows DPAPI.')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def save_mailbox(config):
    encrypted = protect(json.dumps(config).encode('utf-8'))
    temporary = STORE.with_suffix('.dpapi.tmp')
    temporary.write_bytes(encrypted)
    temporary.replace(STORE)


def load_mailbox():
    if not STORE.exists():
        return {}
    try:
        return json.loads(protect(STORE.read_bytes(), decrypt=True).decode('utf-8'))
    except (OSError, ValueError, RuntimeError):
        print('Saved mailbox could not be unlocked. Connect your mailbox again.', flush=True)
        return {}
