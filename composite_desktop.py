"""Open a source sheet read-only in a separate Excel instance."""
from pathlib import Path
import subprocess
import sys
import uuid


def create_sheet_shortcut(path, sheet_name, directory):
    """The foreground Flet client launches the helper, passing foreground rights."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'元Excelが見つかりません：{path}')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        executable = Path(sys.executable)
        arguments = []
        if not getattr(sys, 'frozen', False):
            windowless = executable.with_name('pythonw.exe')
            if windowless.exists():
                executable = windowless
            arguments.append(str(Path(__file__).resolve()))
        arguments += ['--open-sheet', str(path), sheet_name]
        destination = Path(directory) / (uuid.uuid4().hex + '.lnk')
        shortcut = win32com.client.Dispatch('WScript.Shell').CreateShortcut(str(destination))
        shortcut.TargetPath = str(executable)
        shortcut.Arguments = subprocess.list2cmdline(arguments)
        shortcut.WindowStyle = 1
        shortcut.Save()
        shortcut = None
        return destination
    finally:
        pythoncom.CoUninitialize()


def open_sheet(path, sheet_name):
    if not Path(path).is_file():
        raise FileNotFoundError(f'元Excelが見つかりません：{path}')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = book = sheet = None
    try:
        app = win32com.client.DispatchEx('Excel.Application')
        app.AutomationSecurity = 3
        app.EnableEvents = False
        book = app.Workbooks.Open(str(Path(path).resolve()), UpdateLinks=0, ReadOnly=True)
        sheet = book.Worksheets(sheet_name)
        sheet.Activate()
        app.Visible = True
        app.UserControl = True
        app.WindowState = -4137
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.ShowWindow(app.Hwnd, 3)
        user32.SetForegroundWindow(app.Hwnd)
    except Exception:
        if book is not None:
            book.Close(False)
        if app is not None:
            app.Quit()
        raise
    finally:
        sheet = book = app = None
        pythoncom.CoUninitialize()


def run_open_sheet(path, sheet_name):
    try:
        open_sheet(path, sheet_name)
        return 0
    except Exception as exc:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc), '元Excelを開けませんでした', 0x10)
        return 1


if __name__ == '__main__':
    index = sys.argv.index('--open-sheet')
    raise SystemExit(run_open_sheet(*sys.argv[index+1:index+3]))
