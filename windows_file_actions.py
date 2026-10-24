"""Build a private Explorer shortcut for launching from the foreground Flet client.

Python is not the foreground UI process. Flet's UrlLauncher opens the shortcut
from the client process, preserving Explorer's /select command without changing
system foreground settings or guessing which external window to activate.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import uuid


class GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


def _method(pointer, index, *argument_types):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argument_types)(vtable[index])


def _check(result):
    if result < 0:
        raise OSError(f'Windows shortcut error: 0x{result & 0xffffffff:08X}')


def create_explorer_shortcut(pdf_path: str, directory: str) -> Path:
    """Create a .lnk with an explicitly quoted, absolute /select target.

    COM is initialized and released on the calling worker thread. No process is
    started here. The temporary directory is owned by the app session.
    """
    if os.name != 'nt':
        raise OSError('Explorerでの表示はWindows専用です。')
    target = str(Path(pdf_path).absolute())
    if '"' in target or Path(target).suffix.lower() != '.pdf':
        raise ValueError('PDFのパスが正しくありません。')
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / (hashlib.sha256(target.encode('utf-8')).hexdigest() + '.lnk')
    # Separate temporary names allow simultaneous requests for the same target.
    staging = folder / (uuid.uuid4().hex + '.lnk')
    ole32 = ctypes.OleDLL('ole32')
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
                                     wintypes.DWORD, ctypes.POINTER(GUID),
                                     ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    initialized = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    _check(initialized)
    link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        _check(ole32.CoCreateInstance(
            ctypes.byref(GUID('00021401-0000-0000-C000-000000000046')),
            None, 1, ctypes.byref(GUID('000214F9-0000-0000-C000-000000000046')),
            ctypes.byref(link)))
        explorer = str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'explorer.exe')
        _check(_method(link, 20, wintypes.LPCWSTR)(link, explorer))  # SetPath
        _check(_method(link, 11, wintypes.LPCWSTR)(link, f'/select,"{target}"'))
        _check(_method(link, 15, ctypes.c_int)(link, 1))  # SW_SHOWNORMAL
        _check(_method(link, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
            link, ctypes.byref(GUID('0000010B-0000-0000-C000-000000000046')),
            ctypes.byref(persist)))
        _check(_method(persist, 6, wintypes.LPCWSTR, wintypes.BOOL)(persist, str(staging), True))
        os.replace(staging, destination)
        return destination
    finally:
        if persist:
            _method(persist, 2)(persist)
        if link:
            _method(link, 2)(link)
        ole32.CoUninitialize()
        staging.unlink(missing_ok=True)
